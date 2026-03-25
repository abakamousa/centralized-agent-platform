const http = require("http");

const server = http.createServer((req, res) => {
  if (req.method === "GET" && req.url === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "ok" }));
    return;
  }

  if (req.method === "POST" && req.url === "/invoke") {
    const auth = req.headers.authorization;
    const userId = req.headers["x-user-id"] || "unknown-user";

    if (!auth) {
      res.writeHead(401, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ detail: "Missing Authorization header" }));
      return;
    }

    let body = "";
    req.on("data", (chunk) => {
      body += chunk.toString();
    });

    req.on("end", () => {
      const payload = JSON.parse(body || "{}");
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          tool: payload.tool || "unknown-tool",
          status: "success",
          message: `Azure SQL tool handled query for ${userId}`,
        })
      );
    });
    return;
  }

  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ detail: "Not found" }));
});

server.listen(8082, () => {
  console.log("MCP Azure SQL listening on 8082");
});
