"use strict";
const test = require("node:test"), assert = require("node:assert/strict"), http = require("node:http");
const { haLaunch } = require("../setup/runtime.cjs");

for (const scenario of [
  { name: "already-on rejection", screen: 500, want: ["screen", "launch"] },
  { name: "successful dismissal", screen: 200, want: ["screen", "launch"] },
  { name: "screen request disconnects", screen: "disconnect", want: ["screen", "launch"] },
  { name: "option disabled", enabled: false, want: ["launch"] },
  { name: "TV initially off", initial: "off", want: [], error: /off or unavailable/ },
  { name: "TV initially unavailable", initial: "unavailable", want: [], error: /off or unavailable/ },
  { name: "TV switches off after rejection", screen: 500, after: "off", want: ["screen"], error: /no longer active/ },
  { name: "TV unavailable after dismissal", screen: 200, after: "unavailable", want: ["screen"], error: /no longer active/ },
  { name: "state recheck fails", screen: 500, stateError: true, want: ["screen"], error: /no longer active/ },
  { name: "launch failure is not swallowed", screen: 500, launch: 500, want: ["screen", "launch"], error: /did not accept the launch/ },
]) test("screen restoration: " + scenario.name, async (t) => {
  const commands = []; let reads = 0;
  const server = http.createServer(async (req, res) => {
    res.setHeader("Content-Type", "application/json");
    if (req.method === "GET") {
      assert.equal(req.url, "/api/states/media_player.test_tv");
      if (++reads > 1 && scenario.stateError) { res.writeHead(503); return res.end("{}"); }
      return res.end(JSON.stringify({ state: reads === 1 ? scenario.initial || "on" : scenario.after || "on" }));
    }
    assert.equal(req.url, "/api/services/webostv/command");
    let body = ""; for await (const chunk of req) body += chunk;
    const data = JSON.parse(body); assert.equal(data.entity_id, "media_player.test_tv");
    const screen = data.command === "com.webos.service.tvpower/power/turnOnScreen";
    if (!screen) assert.equal(data.command, "system.launcher/launch");
    commands.push(screen ? "screen" : "launch");
    if (screen && scenario.screen === "disconnect") return req.socket.destroy();
    res.writeHead((screen ? scenario.screen : scenario.launch) || 200);
    res.end(screen && scenario.screen === 500 ? JSON.stringify({ error: "The current state must be 'Screen Off'" }) : "[]");
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise(resolve => { server.closeAllConnections(); server.close(resolve); }));
  const run = () => haLaunch({ base: "http://127.0.0.1:" + server.address().port, token: "fixture" },
    { entity_id: "media_player.test_tv", command: "system.launcher/launch", payload: { id: "com.mbs.cameraoverlay" } }, scenario.enabled !== false);
  if (scenario.error) await assert.rejects(run, scenario.error);
  else assert.deepEqual(await run(), { accepted: true });
  assert.deepEqual(commands, scenario.want);
});
