import httpx, asyncio, json, sys

DID = "ttc-1-df5bab8e"

async def check():
    async with httpx.AsyncClient(base_url="http://control-api:8003", timeout=5.0) as c:
        r = await c.get("/events?limit=500")
        events = r.json().get("data", [])
        for ev in events:
            if DID in str(ev.get("identity", "")):
                print("Event:", ev["event_type"], "ts:", ev["ts"])
        
        r2 = await c.get("/quarantine")
        body = r2.json()
        print("Active quarantines:", len(body.get("data", [])))
        print("Epoch:", body.get("epoch"))

asyncio.run(check())
