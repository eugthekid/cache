import { spawn, type ChildProcess } from 'child_process'
import { join } from 'path'
import { existsSync } from 'fs'
import { app } from 'electron'

/**
 * Owns the Python backend's lifecycle in a packaged build.
 *
 * In dev, the backend is started by hand (`backend/run.sh`) and this
 * module deliberately does nothing but wait for it -- that keeps the
 * dev loop's --reload behaviour intact instead of Electron owning a
 * process the developer wants to restart independently.
 *
 * In a packaged build there is no terminal and no venv, so Electron
 * spawns the PyInstaller-frozen executable itself (see
 * backend/backend.spec), waits for it to answer /health, and kills it on
 * quit so nothing is left running after the app closes.
 */

const HOST = '127.0.0.1'
const PORT = 8000
export const BACKEND_URL = `http://${HOST}:${PORT}`

let backendProcess: ChildProcess | null = null

/** Where electron-builder puts the frozen backend (see extraResources).
 * `process.resourcesPath` only exists in a packaged app; in dev this
 * path won't exist, which is exactly the signal to skip spawning. */
function frozenBackendPath(): string {
  return join(process.resourcesPath, 'backend', 'cache-backend')
}

async function isBackendHealthy(): Promise<boolean> {
  try {
    // AbortSignal.timeout so a hung connection fails fast rather than
    // stalling the whole startup poll on one attempt.
    const res = await fetch(`${BACKEND_URL}/health`, { signal: AbortSignal.timeout(2000) })
    return res.ok
  } catch {
    return false
  }
}

/**
 * Resolves once the backend answers /health, or rejects after timing out.
 *
 * The generous timeout is deliberate: a first launch runs every Alembic
 * migration against an empty database before the server binds, which is
 * meaningfully slower than every subsequent launch.
 */
async function waitForHealthy(timeoutMs = 60_000): Promise<void> {
  const startedAt = Date.now()
  while (Date.now() - startedAt < timeoutMs) {
    if (await isBackendHealthy()) return
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  throw new Error(`Backend did not become healthy within ${timeoutMs / 1000}s`)
}

/**
 * Ensures a backend is running and reachable.
 *
 * Checks for an ALREADY-healthy backend first, before considering
 * spawning one. That covers two real cases with one rule: the dev loop
 * (where run.sh owns the process), and a packaged app launched while a
 * backend from a previous run is somehow still alive -- spawning a
 * second one would just fail to bind the port anyway.
 */
export async function ensureBackendRunning(): Promise<void> {
  if (await isBackendHealthy()) return

  const executable = frozenBackendPath()
  if (!existsSync(executable)) {
    // Dev, or a build missing its bundled backend. Nothing to spawn --
    // wait for the developer's own server instead of failing outright.
    await waitForHealthy()
    return
  }

  backendProcess = spawn(executable, [], {
    // Not `shell: true` on purpose: spawning through a shell adds a
    // layer that complicates killing the real process on quit, and the
    // frozen binary needs no shell interpretation to run.
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env }
  })

  backendProcess.stdout?.on('data', (chunk) => console.log(`[backend] ${chunk}`))
  backendProcess.stderr?.on('data', (chunk) => console.error(`[backend] ${chunk}`))
  backendProcess.on('exit', (code, signal) => {
    console.log(`[backend] exited code=${code} signal=${signal}`)
    backendProcess = null
  })

  await waitForHealthy()
}

/**
 * Stops the backend if WE started it.
 *
 * Guarded on backendProcess being set, so quitting the app in dev never
 * kills a backend the developer started in their own terminal.
 */
export function stopBackend(): void {
  if (!backendProcess) return
  backendProcess.kill()
  backendProcess = null
}

// Belt-and-braces against orphaning the child: 'will-quit' covers the
// normal path, but a main-process crash or an external SIGINT/SIGTERM
// would otherwise leave the backend running with no app attached to it.
app.on('will-quit', stopBackend)
process.on('exit', stopBackend)
process.on('SIGINT', () => {
  stopBackend()
  process.exit(0)
})
process.on('SIGTERM', () => {
  stopBackend()
  process.exit(0)
})
