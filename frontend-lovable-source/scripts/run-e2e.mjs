import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { createServer as createHttpServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, resolve } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const host = "127.0.0.1";
const port = 4174;
const baseURL = `http://${host}:${port}`;
const backendPort = 4175;
const backendURL = `http://${host}:${backendPort}`;
const realBackend = process.env.PLAYWRIGHT_REAL_BACKEND === "1";
const repoRoot = fileURLToPath(new URL("../../", import.meta.url));
const publicRoot = fileURLToPath(new URL("../.output/public/", import.meta.url));
const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webmanifest": "application/manifest+json; charset=utf-8",
};

const e2eSupabaseURL = `${baseURL}/__e2e/supabase`;
const e2eSupabaseKey = "sb_publishable_e2e_only";

process.env.VITE_E2E_MODE = "1";
process.env.VITE_SUPABASE_URL = e2eSupabaseURL;
process.env.VITE_SUPABASE_PUBLISHABLE_KEY = e2eSupabaseKey;
// TanStack Start's generated Supabase integration reads the unprefixed names
// during SSR and newer Vite builds also use them for the client fallback.
process.env.SUPABASE_URL = e2eSupabaseURL;
process.env.SUPABASE_PUBLISHABLE_KEY = e2eSupabaseKey;
process.env.SUPABASE_SERVICE_ROLE_KEY = "sb_secret_e2e_only";
// Firefox can deadlock in headless software WebRender on Windows/CI hosts.
process.env.MOZ_WEBRENDER = "0";

let child;
let backendChild;
let server;
let integrationRoot;
let shuttingDown = false;

async function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  if (child && child.exitCode === null) child.kill(signal);
  if (backendChild && backendChild.exitCode === null) {
    backendChild.kill(signal);
    await Promise.race([
      new Promise((resolve) => backendChild.once("exit", resolve)),
      new Promise((resolve) => setTimeout(resolve, 3_000)),
    ]);
  }
  if (server) {
    server.closeAllConnections?.();
    await new Promise((resolve) => server.close(resolve));
  }
  if (integrationRoot) await rm(integrationRoot, { recursive: true, force: true });
}

process.once("SIGINT", () => void shutdown("SIGINT"));
process.once("SIGTERM", () => void shutdown("SIGTERM"));

try {
  if (realBackend) {
    integrationRoot = await mkdtemp(resolve(tmpdir(), "spareno-realtime-e2e-"));
    const databasePath = resolve(integrationRoot, "integration.sqlite3").replaceAll("\\", "/");
    const python = process.env.PYTHON || "python";
    const backendEnv = {
      ...process.env,
      PYTHONPATH: repoRoot,
      DATABASE_URL: `sqlite:///${databasePath}`,
      DATA_DIR: resolve(integrationRoot, "data"),
      AUTO_CREATE_SCHEMA: "true",
      APP_ENV: "test",
    };
    const seed = spawn(python, [resolve(repoRoot, "scripts/seed_realtime_e2e.py")], {
      cwd: repoRoot,
      stdio: "inherit",
      env: backendEnv,
    });
    const seedExitCode = await new Promise((resolve, reject) => {
      seed.once("error", reject);
      seed.once("exit", (code) => resolve(code ?? 1));
    });
    if (seedExitCode !== 0) throw new Error(`Backend integration seed failed with exit code ${seedExitCode}`);
    backendChild = spawn(
      python,
      ["-m", "uvicorn", "app.api_main:app", "--host", host, "--port", String(backendPort), "--no-access-log"],
      { cwd: repoRoot, stdio: "inherit", env: backendEnv },
    );
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline) {
      if (backendChild.exitCode !== null) throw new Error(`Backend exited with code ${backendChild.exitCode}`);
      try {
        const health = await fetch(`${backendURL}/health`);
        if (health.ok) break;
      } catch { /* backend is still starting */ }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    const health = await fetch(`${backendURL}/health`).catch(() => null);
    if (!health?.ok) throw new Error("Backend integration server did not become ready");
  }
  child = spawn(process.execPath, ["./node_modules/vite/bin/vite.js", "build"], {
    stdio: "inherit",
    env: process.env,
  });
  const buildExitCode = await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code) => resolve(code ?? 1));
  });
  child = undefined;
  if (buildExitCode !== 0) throw new Error(`Production build failed with exit code ${buildExitCode}`);
  const workerURL = new URL("../.output/server/index.mjs", import.meta.url);
  workerURL.searchParams.set("build", String(Date.now()));
  const worker = (await import(workerURL.href)).default;
  const assets = {
    async fetch(request) {
      const pathname = decodeURIComponent(new URL(request.url).pathname);
      const target = resolve(publicRoot, `.${pathname}`);
      if (!target.startsWith(publicRoot)) return new Response("Not found", { status: 404 });
      try {
        const body = await readFile(target);
        return new Response(body, {
          headers: { "content-type": contentTypes[extname(target)] ?? "application/octet-stream" },
        });
      } catch {
        return new Response("Not found", { status: 404 });
      }
    },
  };
  server = createHttpServer(async (incoming, outgoing) => {
    try {
      const headers = new Headers();
      for (const [name, value] of Object.entries(incoming.headers)) {
        if (Array.isArray(value)) value.forEach((item) => headers.append(name, item));
        else if (value !== undefined) headers.set(name, value);
      }
      const hasBody = !["GET", "HEAD"].includes(incoming.method ?? "GET");
      const body = hasBody
        ? await new Promise((resolve, reject) => {
            const chunks = [];
            incoming.on("data", (chunk) => chunks.push(chunk));
            incoming.on("end", () => resolve(Buffer.concat(chunks)));
            incoming.on("error", reject);
          })
        : undefined;
      const incomingURL = new URL(incoming.url ?? "/", baseURL);
      if (realBackend && (
        incomingURL.pathname === "/health"
        || incomingURL.pathname.startsWith("/api/")
        || incomingURL.pathname.startsWith("/media/")
      )) {
        headers.set("host", `${host}:${backendPort}`);
        const response = await fetch(new URL(incomingURL.pathname + incomingURL.search, backendURL), {
          method: incoming.method,
          headers,
          body,
          duplex: hasBody ? "half" : undefined,
          redirect: "manual",
        });
        const responseHeaders = Object.fromEntries(response.headers);
        delete responseHeaders.connection;
        delete responseHeaders["transfer-encoding"];
        delete responseHeaders["content-length"];
        outgoing.writeHead(response.status, responseHeaders);
        if (response.body) {
          for await (const chunk of response.body) outgoing.write(Buffer.from(chunk));
        }
        outgoing.end();
        return;
      }
      const request = new Request(new URL(incoming.url ?? "/", baseURL), {
        method: incoming.method,
        headers,
        body,
        duplex: hasBody ? "half" : undefined,
      });
      const pending = [];
      const response = await worker.fetch(request, { ASSETS: assets }, {
        waitUntil: (promise) => pending.push(promise),
        passThroughOnException() {},
      });
      outgoing.writeHead(response.status, Object.fromEntries(response.headers));
      outgoing.end(Buffer.from(await response.arrayBuffer()));
      void Promise.allSettled(pending);
    } catch (error) {
      if (!shuttingDown) console.error(error);
      if (!outgoing.headersSent && !outgoing.destroyed) {
        outgoing.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
        outgoing.end("E2E preview server error");
      } else if (!outgoing.destroyed) {
        outgoing.destroy();
      }
    }
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, resolve);
  });
  child = spawn(
    process.execPath,
    ["./node_modules/@playwright/test/cli.js", "test", ...process.argv.slice(2)],
    {
      stdio: "inherit",
      env: { ...process.env, PLAYWRIGHT_EXTERNAL_SERVER: "1" },
    },
  );
  const exitCode = await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code) => resolve(code ?? 1));
  });
  process.exitCode = exitCode;
} finally {
  await shutdown("SIGTERM");
}

// The imported Nitro worker can keep internal timers alive after Playwright has
// finished. At this point both the test child and HTTP server are closed, so
// propagate the test result instead of leaving CI waiting on those handles.
process.exit(process.exitCode ?? 0);
