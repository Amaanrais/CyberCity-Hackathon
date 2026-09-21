import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app, plant_sim, interlock, state_mgr, controller


@pytest.mark.asyncio
async def test_get_state():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/state")
        assert response.status_code == 200
        data = response.json()
        assert "run_id" in data
        assert "sensors" in data
        assert "control" in data
        assert "history" in data
        assert data["interlock_on"] is True
        assert data["system_status"] in ["NOMINAL", "BLOCKED", "DANGER"]


@pytest.mark.asyncio
async def test_interlock_toggle():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Toggle OFF
        res = await ac.post("/interlock", json={"enabled": False})
        assert res.status_code == 200
        assert res.json()["interlock_on"] is False

        state = await ac.get("/state")
        assert state.json()["interlock_on"] is False

        # Toggle back ON
        res2 = await ac.post("/interlock", json={"enabled": True})
        assert res2.status_code == 200
        assert res2.json()["interlock_on"] is True


@pytest.mark.asyncio
async def test_oldsmar_spike_attack_blocked_when_interlock_on():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Ensure reset & interlock ON
        await ac.post("/reset")
        await ac.post("/interlock", json={"enabled": True})

        # Trigger Oldsmar spike
        res = await ac.post("/attack/oldsmar_spike")
        assert res.status_code == 200

        # Step controller tick
        controller.step_tick()
        controller.step_tick()

        # Check /state
        state_res = await ac.get("/state")
        data = state_res.json()
        assert data["sensors"]["primary_ppm"] >= 11000.0
        assert data["control"]["requested_dose_ppm"] >= 11000.0
        # Actual dose must remain safe!
        assert data["control"]["actual_dose_ppm"] <= 150.0
        assert data["last_decision"]["decision"] == "BLOCKED"
        assert data["system_status"] == "BLOCKED"


@pytest.mark.asyncio
async def test_oldsmar_spike_attack_succeeds_when_interlock_off():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Reset and toggle interlock OFF
        await ac.post("/reset")
        await ac.post("/interlock", json={"enabled": False})

        # Trigger Oldsmar spike
        await ac.post("/attack/oldsmar_spike")

        # Step controller ticks to let physical lag advance
        for _ in range(15):
            controller.step_tick()

        state_res = await ac.get("/state")
        data = state_res.json()
        # Actual dose shoots to 11,100!
        assert data["control"]["actual_dose_ppm"] >= 11000.0
        # pH climbs well into dangerous band (> 10.0)!
        assert data["control"]["ph"] > 10.0
        assert data["system_status"] == "DANGER"

        # Cleanup: reset system
        await ac.post("/reset")
        await ac.post("/interlock", json={"enabled": True})


@pytest.mark.asyncio
async def test_runs_and_audit():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/runs")
        assert res.status_code == 200
        runs = res.json()
        assert isinstance(runs, list)
        if runs:
            run_id = runs[0]["run_id"]
            dec_res = await ac.get(f"/runs/{run_id}/decisions")
            assert dec_res.status_code == 200
            assert "decisions" in dec_res.json()
