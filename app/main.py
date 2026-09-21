import os
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.attacks import AttackEngine
from app.audit import AuditSink
from app.controller import PlantController
from app.interlock import SafetyInterlock
from app.models import (
    InjectValueRequest,
    InterlockToggleRequest,
    SystemStateResponse,
    EventItem,
    RunSummary,
    EventType
)
from app.plant import PlantSimulator
from app.state import SystemStateManager

# Instantiate application singletons
plant_sim = PlantSimulator(seed=42)
interlock = SafetyInterlock()
state_mgr = SystemStateManager()
audit_sink = AuditSink(db_path="data/audit.db")
attack_engine = AttackEngine(plant_sim=plant_sim, state_mgr=state_mgr)
controller = PlantController(
    plant_sim=plant_sim,
    interlock=interlock,
    state_mgr=state_mgr,
    audit_sink=audit_sink
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: launch background SQLite writer and 1Hz control loop
    await audit_sink.start()
    await controller.start()
    yield
    # Shutdown: cleanly terminate loops
    attack_engine.stop_active_attacks()
    await controller.stop()
    await audit_sink.stop()


app = FastAPI(
    title="AquaLock SIS — Chemical Dosing Safety Interlock",
    description="AquaLock SIS: Cyber-physical water safety instrumented system defending SCADA chemical dosing from sensor tampering (IEC 61511 / IEC 62443)",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for local testing and developer tooling
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/state", response_model=SystemStateResponse)
async def get_state(since_event_id: Optional[int] = Query(None, description="Only return events after this ID")):
    """
    Unified atomic snapshot of the entire plant, control loop, and safety interlock.
    Served entirely from in-memory ring buffers with zero disk I/O.
    """
    return state_mgr.get_snapshot(plant_sim=plant_sim, interlock=interlock, since_event_id=since_event_id)


@app.post("/interlock")
async def toggle_interlock(payload: InterlockToggleRequest):
    """
    Physical SIS Key Switch Stand-In.
    Toggles the independent Safety Instrumented System interlock between ON and OFF.
    """
    interlock.enabled = payload.enabled
    status_str = "ENGAGED (ACTIVE PROTECTION)" if payload.enabled else "BYPASSED (SAFETY DISABLED)"
    state_mgr.add_event(
        EventType.INFO,
        f"SIS KEY SWITCH: {status_str}",
        f"Physical hardware key switch set to {payload.enabled}."
    )
    return {
        "status": "success",
        "interlock_on": interlock.enabled,
        "mode": status_str
    }


@app.post("/reset")
async def reset_system():
    """
    Resets in-memory plant simulation, reseeds the RNG, clears active attacks,
    and initializes a new run_id. Historical SQLite audit records are preserved.
    """
    attack_engine.stop_active_attacks()
    plant_sim.reset(seed=42)
    interlock.reset()
    state_mgr.reset(new_run=True)
    return {
        "status": "success",
        "message": "System reset to nominal 100.0 ppm baseline with new run ID",
        "run_id": state_mgr.run_id
    }


@app.post("/sensors/primary/inject")
async def inject_primary(payload: InjectValueRequest):
    """
    Attacker endpoint: Compromise primary sensor reading fed to the SCADA controller.
    """
    plant_sim.inject_primary(payload.value)
    state_mgr.add_event(
        EventType.ATTACK,
        "PRIMARY SENSOR INJECTION",
        f"Attacker set primary sensor to {payload.value:.1f} ppm."
    )
    state_mgr.add_annotation(f"INJECT Primary={payload.value:.1f}", "ATTACK", "#ef4444")
    return {"status": "success", "channel": "primary", "injected_value": payload.value}


@app.post("/sensors/flow/inject")
async def inject_flow(payload: InjectValueRequest):
    """
    Attacker endpoint: Compromise reported flow rate to force controller mass calculation error.
    """
    plant_sim.inject_flow(payload.value)
    state_mgr.add_event(
        EventType.ATTACK,
        "FLOW SENSOR INJECTION",
        f"Attacker falsified reported flow to {payload.value:.1f} L/s."
    )
    state_mgr.add_annotation(f"INJECT Flow={payload.value:.1f}", "ATTACK", "#06b6d4")
    return {"status": "success", "channel": "flow", "injected_value": payload.value}


@app.post("/sensors/verification/inject")
async def inject_verification(payload: InjectValueRequest):
    """
    Attacker endpoint: Compromise secondary verification channel (Dual-Compromise variant only).
    """
    plant_sim.inject_verification(payload.value)
    state_mgr.add_event(
        EventType.ATTACK,
        "VERIFICATION SENSOR INJECTION",
        f"Secondary verification channel falsified to {payload.value:.1f} ppm."
    )
    state_mgr.add_annotation(f"INJECT Verif={payload.value:.1f}", "ATTACK", "#8b5cf6")
    return {"status": "success", "channel": "verification", "injected_value": payload.value}


@app.post("/attack/{variant}")
async def launch_attack(variant: str):
    """
    Triggers one of the 4 cyberattack scenarios:
    - oldsmar_spike: 100 -> 11,100 ppm jump
    - single_channel_stealth: moderate 135 ppm primary shift
    - slow_ramp: dual-compromise +35 ppm/s ramp
    - flow_falsification: flow reported at 15 L/s
    - stop: cancels all active attacks and restores nominal sensors
    """
    if variant == "stop" or variant == "nominal":
        attack_engine.stop_active_attacks()
        state_mgr.add_event(
            EventType.INFO,
            "ATTACK CANCELLED",
            "Sensors restored to nominal physical simulation."
        )
        return {"status": "success", "message": "All attacks stopped and sensors restored"}

    res = await attack_engine.trigger_attack(variant)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@app.get("/events", response_model=List[EventItem])
async def get_events(since_id: Optional[int] = Query(None)):
    """
    Returns recent in-memory event logs.
    """
    if since_id is not None:
        return [e for e in state_mgr.events if e.id > since_id]
    return state_mgr.events


@app.get("/runs", response_model=List[RunSummary])
async def get_runs():
    """
    Queries historical runs from the SQLite audit sink.
    """
    return audit_sink.get_runs()


@app.get("/runs/{run_id}/decisions")
async def get_run_decisions(run_id: str, limit: int = Query(500, le=2000)):
    """
    Queries detailed audit records for a given run ID from the SQLite sink.
    """
    records = audit_sink.get_run_decisions(run_id, limit=limit)
    return {"run_id": run_id, "count": len(records), "decisions": records}


# Mount static files and serve dashboard
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
async def serve_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "AquaLock SIS Safety Interlock API is running. Dashboard HTML will be served here."}
