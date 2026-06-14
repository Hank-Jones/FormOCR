use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{Manager, Theme, window::Color};

/// Matches `--bg` in `src/styles.css`.
const WINDOW_BG: Color = Color(7, 11, 18, 255);

#[cfg(windows)]
fn sync_window_chrome(window: &tauri::WebviewWindow) {
    let _ = window.set_theme(Some(Theme::Dark));
    let _ = window.set_background_color(Some(WINDOW_BG));
}

struct SidecarState {
    ollama: Mutex<Option<Child>>,
    api: Mutex<Option<Child>>,
    api_port: Mutex<u16>,
    /// Port FormOCR owns (11435). Cleared when using foreign Ollama on 11434.
    managed_ollama_port: Mutex<Option<u16>>,
    startup: Mutex<StartupStatus>,
    /// Path to api-server.log written during this session.
    api_log_path: Mutex<Option<PathBuf>>,
}

#[derive(Clone, Serialize, Default)]
struct StartupStatus {
    phase: String,
    message: String,
    ready: bool,
    progress: u8,
    error: Option<String>,
}

const SEED_MARKER: &str = ".offline-seed-v1";
const INSTALL_READY: &str = ".install-ready-v1";
const API_PORT_FILE: &str = "api.port";
const DEFAULT_API_PORT: u16 = 8765;
const OLLAMA_PORT_DEFAULT: u16 = 11434;
const OLLAMA_PORT_FORMOCR: u16 = 11435;
const OLLAMA_MODELS_REQUIRED: &[&str] = &["qwen2.5vl:3b"];

fn local_data_dir() -> PathBuf {
    std::env::var("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."))
        .join("FormOCR")
}

fn models_dir() -> PathBuf {
    local_data_dir().join("models")
}

fn ollama_models_dir() -> PathBuf {
    models_dir().join("ollama")
}

fn set_startup(
    state: &tauri::State<'_, SidecarState>,
    phase: &str,
    message: &str,
    ready: bool,
    progress: u8,
    error: Option<&str>,
) {
    let mut s = state.startup.lock().unwrap();
    s.phase = phase.to_string();
    s.message = message.to_string();
    s.ready = ready;
    s.progress = progress.min(100);
    s.error = error.map(|e| e.to_string());
}

fn read_api_port() -> u16 {
    let path = local_data_dir().join(API_PORT_FILE);
    fs::read_to_string(&path)
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(DEFAULT_API_PORT)
}

fn install_prepared() -> bool {
    local_data_dir().join(INSTALL_READY).exists() && models_dir().join(SEED_MARKER).exists()
}

#[derive(Debug, Deserialize)]
struct HealthResponse {
    ocr_ready: bool,
    #[serde(default)]
    ocr_error: Option<String>,
    #[serde(default)]
    ollama_on_gpu: Option<bool>,
    #[serde(default)]
    ollama_vram_mb: Option<u32>,
}

fn fetch_health(port: u16) -> Option<HealthResponse> {
    let url = format!("http://127.0.0.1:{port}/health");
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(8))
        .build()
        .ok()?;
    let resp = client.get(&url).send().ok()?;
    if !resp.status().is_success() {
        return None;
    }
    resp.json().ok()
}

fn stop_orphan_api_server(state: &SidecarState) {
    if let Some(mut child) = state.api.lock().unwrap().take() {
        let _ = child.kill();
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        let _ = Command::new("taskkill")
            .args(["/F", "/IM", "api-server.exe"])
            .creation_flags(0x08000000)
            .status();
    }
    thread::sleep(Duration::from_millis(600));
}

fn wait_http_ok(url: &str, attempts: u32) -> bool {
    let client = match reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
    {
        Ok(c) => c,
        Err(_) => return false,
    };
    for _ in 0..attempts {
        if client
            .get(url)
            .send()
            .map(|r| r.status().is_success())
            .unwrap_or(false)
        {
            return true;
        }
        std::thread::sleep(Duration::from_millis(400));
    }
    false
}

fn dir_has_files(path: &Path) -> bool {
    if path.is_file() {
        return true;
    }
    fs::read_dir(path)
        .ok()
        .map(|entries| {
            entries.flatten().any(|e| {
                let p = e.path();
                p.is_file() || (p.is_dir() && dir_has_files(&p))
            })
        })
        .unwrap_or(false)
}

/// Resolve bundled files. On Windows, Tauri `Resource` is the exe directory (not `resources/`).
/// Offline installs historically used `resources/binaries/...` — try both layouts.
fn resolve_resource_path(app: &tauri::AppHandle, rel: &str) -> Option<PathBuf> {
    let rel = rel.replace('\\', "/");
    let candidates = [rel.as_str(), &format!("resources/{rel}")];

    for candidate in &candidates {
        if let Ok(p) = app
            .path()
            .resolve(candidate, tauri::path::BaseDirectory::Resource)
        {
            if p.exists() {
                return Some(p);
            }
        }
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            for candidate in &candidates {
                let p = dir.join(candidate.replace('/', std::path::MAIN_SEPARATOR_STR));
                if p.exists() {
                    return Some(p);
                }
            }
        }
    }

    None
}

fn seed_from_resources(app: &tauri::AppHandle, name: &str) -> Option<PathBuf> {
    resolve_resource_path(app, &format!("seed/{name}"))
        .filter(|p| p.is_dir() && dir_has_files(p))
}

fn ollama_manifest_path(models_root: &Path, model: &str) -> PathBuf {
    let (name, tag) = model
        .split_once(':')
        .map(|(n, t)| (n, t))
        .unwrap_or((model, "latest"));
    models_root
        .join("manifests")
        .join("registry.ollama.ai")
        .join("library")
        .join(name)
        .join(tag)
}

fn ensure_ollama_model_from_seed(app: &tauri::AppHandle, model: &str) {
    let Some(src) = seed_from_resources(app, "ollama") else {
        return;
    };
    let dst = ollama_models_dir();
    let dst_manifest = ollama_manifest_path(&dst, model);
    if dst_manifest.exists() {
        return;
    }
    let src_manifest = ollama_manifest_path(&src, model);
    if !src_manifest.exists() {
        return;
    }
    let _ = fs::create_dir_all(dst.join("blobs"));
    if let Some(parent) = dst_manifest.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let _ = fs::copy(&src_manifest, &dst_manifest);
    let Ok(raw) = fs::read_to_string(&dst_manifest) else {
        return;
    };
    let Ok(json) = serde_json::from_str::<serde_json::Value>(&raw) else {
        return;
    };
    let mut digests: Vec<String> = Vec::new();
    if let Some(d) = json.get("config").and_then(|c| c.get("digest")).and_then(|v| v.as_str()) {
        digests.push(d.to_string());
    }
    if let Some(layers) = json.get("layers").and_then(|v| v.as_array()) {
        for layer in layers {
            if let Some(d) = layer.get("digest").and_then(|v| v.as_str()) {
                digests.push(d.to_string());
            }
        }
    }
    for digest in digests {
        let hash = digest.trim_start_matches("sha256:");
        let blob_name = format!("sha256-{hash}");
        let src_blob = src.join("blobs").join(&blob_name);
        let dst_blob = dst.join("blobs").join(&blob_name);
        if src_blob.is_file() && !dst_blob.exists() {
            let _ = fs::copy(&src_blob, &dst_blob);
        }
    }
}

fn ensure_offline_models_seeded(app: &tauri::AppHandle) {
    let marker = models_dir().join(SEED_MARKER);
    let first_seed = !marker.exists();

    let _ = fs::create_dir_all(models_dir());

    for model in OLLAMA_MODELS_REQUIRED {
        ensure_ollama_model_from_seed(app, model);
    }

    if first_seed && dir_has_files(&ollama_models_dir()) {
        let _ = fs::write(marker, "ok");
    }
}

#[cfg(windows)]
fn configure_hidden(cmd: &mut Command) {
    use std::os::windows::process::CommandExt;
    cmd.creation_flags(0x08000000);
}

#[cfg(not(windows))]
fn configure_hidden(_cmd: &mut Command) {}

fn resolve_resource_bin(app: &tauri::AppHandle, rel: &str) -> Option<PathBuf> {
    resolve_resource_path(app, rel).filter(|p| p.is_file())
}

fn ollama_tags_url(port: u16) -> String {
    format!("http://127.0.0.1:{port}/api/tags")
}

fn ollama_port_has_required_models(port: u16) -> bool {
    let client = match reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(3))
        .build()
    {
        Ok(c) => c,
        Err(_) => return false,
    };
    let Ok(resp) = client.get(ollama_tags_url(port)).send() else {
        return false;
    };
    if !resp.status().is_success() {
        return false;
    }
    let Ok(body) = resp.text() else {
        return false;
    };
    OLLAMA_MODELS_REQUIRED.iter().all(|m| {
        let base = m.split(':').next().unwrap_or(m);
        body.contains(m) || body.contains(base)
    })
}

/// GPU inference needs `lib/ollama` (CUDA runners) beside ollama.exe.
/// FormOCR historically copied only ollama.exe, which silently falls back to CPU.
fn ollama_has_gpu_libs(exe: &Path) -> bool {
    exe.parent()
        .map(|d| d.join("lib").join("ollama").is_dir())
        .unwrap_or(false)
}

fn system_ollama_candidates() -> Vec<PathBuf> {
    let mut out = Vec::new();
    if let Ok(lad) = std::env::var("LOCALAPPDATA") {
        out.push(
            PathBuf::from(&lad)
                .join("Programs")
                .join("Ollama")
                .join("ollama.exe"),
        );
    }
    out.push(PathBuf::from(r"C:\Program Files\Ollama\ollama.exe"));
    out
}

fn ollama_port_open(port: u16) -> bool {
    wait_http_ok(&ollama_tags_url(port), 1)
}

fn resolve_ollama_exe(app: &tauri::AppHandle) -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    // Prefer FormOCR-owned copies so exit cleanup does not leave tray Ollama running.
    if let Some(p) = resolve_resource_bin(app, "binaries/ollama.exe") {
        candidates.push(p);
    }
    if let Ok(lad) = std::env::var("LOCALAPPDATA") {
        candidates.push(
            PathBuf::from(&lad)
                .join("Programs")
                .join("FormOCR")
                .join("binaries")
                .join("ollama.exe"),
        );
    }
    candidates.extend(system_ollama_candidates());
    for p in &candidates {
        if ollama_has_gpu_libs(p) {
            return Some(p.clone());
        }
    }
    candidates.into_iter().find(|p| p.is_file())
}

fn configure_ollama_gpu(cmd: &mut Command, ollama_dir: &Path) {
    let mut path = std::env::var("PATH").unwrap_or_default();
    let dir = ollama_dir.to_string_lossy();
    if !path.split(';').any(|part| part.eq_ignore_ascii_case(dir.as_ref())) {
        path = format!("{dir};{path}");
    }
    cmd.env("PATH", path);
    cmd.env("CUDA_VISIBLE_DEVICES", "0")
        .env("OLLAMA_FLASH_ATTENTION", "1")
        .env("OLLAMA_MAX_LOADED_MODELS", "1")
        .env("OLLAMA_KEEP_ALIVE", "30m")
        .env("OLLAMA_NUM_PARALLEL", "1");
    // Do not set OLLAMA_LLM_LIBRARY — let Ollama pick cuda from lib/ollama.
}

#[cfg(windows)]
fn win_kill_process_tree(pid: u32) {
    use std::os::windows::process::CommandExt;
    let _ = Command::new("taskkill")
        .args(["/F", "/T", "/PID", &pid.to_string()])
        .creation_flags(0x08000000)
        .status();
}

#[cfg(not(windows))]
fn win_kill_process_tree(_pid: u32) {}

#[cfg(windows)]
fn win_kill_listeners_on_port(port: u16) {
    use std::os::windows::process::CommandExt;
    let ps = format!(
        "$p = {port}; \
         Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | \
         ForEach-Object {{ taskkill /F /T /PID $_.OwningProcess 2>$null | Out-Null }}"
    );
    let _ = Command::new("powershell")
        .args(["-NoProfile", "-NonInteractive", "-Command", &ps])
        .creation_flags(0x08000000)
        .status();
    thread::sleep(Duration::from_millis(400));
}

#[cfg(not(windows))]
fn win_kill_listeners_on_port(_port: u16) {}

fn stop_managed_ollama_on_port(state: &SidecarState, port: u16) {
    if let Some(mut child) = state.ollama.lock().unwrap().take() {
        let pid = child.id();
        let _ = child.kill();
        win_kill_process_tree(pid);
        thread::sleep(Duration::from_millis(200));
    }
    for _ in 0..5 {
        if !ollama_port_open(port) {
            break;
        }
        win_kill_listeners_on_port(port);
        thread::sleep(Duration::from_millis(350));
    }
}

/// Start (or restart) FormOCR-owned Ollama — never attach to a foreign CPU instance.
fn ensure_ollama_on_port(app: &tauri::AppHandle, state: &SidecarState, port: u16) {
    *state.managed_ollama_port.lock().unwrap() = Some(port);

    if state.ollama.lock().unwrap().is_some() {
        if wait_http_ok(&ollama_tags_url(port), 2) {
            return;
        }
        stop_managed_ollama_on_port(state, port);
    } else if wait_http_ok(&ollama_tags_url(port), 1) {
        // Orphan from a previous FormOCR session — reclaim the port.
        stop_managed_ollama_on_port(state, port);
    }

    if let Some(child) = spawn_ollama_on_port(app, port) {
        *state.ollama.lock().unwrap() = Some(child);
    }
    let _ = wait_http_ok(&ollama_tags_url(port), 30);
}

fn spawn_ollama_on_port(app: &tauri::AppHandle, port: u16) -> Option<Child> {
    let exe = resolve_ollama_exe(app)?;
    let ollama_dir = exe.parent()?.to_path_buf();

    let models = ollama_models_dir();
    let _ = fs::create_dir_all(&models);

    let mut cmd = Command::new(&exe);
    cmd.current_dir(&ollama_dir)
        .arg("serve")
        .env("OLLAMA_HOST", format!("127.0.0.1:{port}"))
        .env("OLLAMA_MODELS", &models);
    configure_ollama_gpu(&mut cmd, &ollama_dir);
    cmd.stdout(Stdio::null()).stderr(Stdio::null());
    configure_hidden(&mut cmd);
    cmd.spawn().ok()
}

fn resolve_ollama_port(app: &tauri::AppHandle, state: &SidecarState) -> u16 {
    // Always spawn FormOCR-owned Ollama on 11435 with our model dir + GPU-capable exe.
    // Never attach to tray Ollama on 11434 — different models path and env.
    if resolve_ollama_exe(app).is_some() {
        ensure_ollama_on_port(app, state, OLLAMA_PORT_FORMOCR);
        return OLLAMA_PORT_FORMOCR;
    }
    if ollama_port_has_required_models(OLLAMA_PORT_DEFAULT) {
        return OLLAMA_PORT_DEFAULT;
    }
    ensure_ollama_on_port(app, state, OLLAMA_PORT_FORMOCR);
    OLLAMA_PORT_FORMOCR
}

fn api_log_path() -> PathBuf {
    local_data_dir().join("api-server.log")
}

fn read_api_log_tail(lines: usize) -> String {
    fs::read_to_string(api_log_path())
        .unwrap_or_default()
        .lines()
        .rev()
        .take(lines)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect::<Vec<_>>()
        .join("\n")
}

fn spawn_api(app: &tauri::AppHandle, port: u16, ollama_port: u16) -> Option<Child> {
    let data_dir = local_data_dir();
    let _ = fs::create_dir_all(&data_dir);

    let api_exe = resolve_resource_bin(app, "binaries/api-server/api-server.exe");

    let mut cmd = if let Some(exe) = api_exe {
        let mut c = Command::new(&exe);
        if let Some(dir) = exe.parent() {
            c.current_dir(dir);
        }
        c
    } else {
        let api_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("api");
        let mut c = Command::new("python");
        c.args([
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            &format!("--port={port}"),
        ])
        .current_dir(api_dir);
        c
    };

    let ollama_host = format!("http://127.0.0.1:{ollama_port}");

    // Pipe api-server stdout+stderr to a log file so crashes are diagnosable.
    let log_file = fs::OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(api_log_path())
        .ok();
    let (stdout_cfg, stderr_cfg) = if let Some(f) = log_file {
        match f.try_clone() {
            Ok(f2) => (Stdio::from(f), Stdio::from(f2)),
            Err(_) => (Stdio::null(), Stdio::null()),
        }
    } else {
        (Stdio::null(), Stdio::null())
    };

    cmd.env("FORMOCR_DATA_DIR", data_dir.to_string_lossy().to_string())
        .env("FORMOCR_PORT", port.to_string())
        .env("FORMOCR_OLLAMA_HOST", &ollama_host)
        .env("FORMOCR_OCR_ENGINE", "qwen")
        .env("FORMOCR_HANDWRITING_OCR_ENABLED", "true")
        .env("FORMOCR_HANDWRITING_OCR_MODEL", "qwen2.5vl:3b")
        .env("FORMOCR_AI_CORRECTION_ENABLED", "false")
        .stdout(stdout_cfg)
        .stderr(stderr_cfg);
    configure_hidden(&mut cmd);
    cmd.spawn().ok()
}

fn stop_sidecars(state: &SidecarState) {
    let mut stopped_api_child = false;
    if let Some(mut child) = state.api.lock().unwrap().take() {
        let pid = child.id();
        let _ = child.kill();
        win_kill_process_tree(pid);
        stopped_api_child = true;
    }
    #[cfg(windows)]
    if stopped_api_child {
        use std::os::windows::process::CommandExt;
        let _ = Command::new("taskkill")
            .args(["/F", "/IM", "api-server.exe"])
            .creation_flags(0x08000000)
            .status();
    }

    if let Some(ollama_port) = state.managed_ollama_port.lock().unwrap().take() {
        stop_managed_ollama_on_port(state, ollama_port);
    }
}

fn parse_dev_api_port() -> Option<u16> {
    let url = std::env::var("FORMOCR_DEV_API").ok()?;
    let port_str = url.rsplit(':').next()?.trim_end_matches('/');
    port_str.parse().ok()
}

fn wait_for_api_ready(port: u16, max_attempts: u32) -> Option<HealthResponse> {
    wait_for_api_ready_with_child(port, max_attempts, None)
}

fn wait_for_api_ready_with_child(
    port: u16,
    max_attempts: u32,
    child: Option<&Mutex<Option<Child>>>,
) -> Option<HealthResponse> {
    for i in 0..max_attempts {
        // If we own the child process and it already exited, stop waiting immediately.
        if let Some(child_mutex) = child {
            if let Ok(mut guard) = child_mutex.try_lock() {
                if let Some(ref mut c) = *guard {
                    if let Ok(Some(_)) = c.try_wait() {
                        // Process exited — API will never come up.
                        return None;
                    }
                }
            }
        }
        if let Some(h) = fetch_health(port) {
            if h.ocr_ready {
                return Some(h);
            }
        }
        if i % 5 == 0 {
            thread::sleep(Duration::from_millis(400));
        } else {
            thread::sleep(Duration::from_millis(800));
        }
    }
    fetch_health(port)
}

fn bootstrap_production(handle: tauri::AppHandle) {
    let state = handle.state::<SidecarState>();
    let port = read_api_port();
    *state.api_port.lock().unwrap() = port;

    set_startup(
        &state,
        "init",
        "Starting…",
        false,
        5,
        None,
    );

    if !install_prepared() {
        set_startup(
            &state,
            "models",
            "Installing models…",
            false,
            15,
            None,
        );
        ensure_offline_models_seeded(&handle);
    }

    if let Some(h) = fetch_health(port) {
        if h.ocr_ready {
            set_startup(
                &state,
                "ready",
                "Ready",
                true,
                100,
                None,
            );
            return;
        }
        if h.ocr_error.as_ref().is_some_and(|e| !e.is_empty()) {
            stop_orphan_api_server(&state);
        } else {
            set_startup(
                &state,
                "vision",
                "Loading vision model…",
                false,
                70,
                None,
            );
            if wait_for_api_ready(port, 120).is_some_and(|x| x.ocr_ready) {
                set_startup(&state, "ready", "Ready", true, 100, None);
            } else {
                set_startup(
                    &state,
                    "ready",
                    "Ready",
                    true,
                    95,
                    Some("Vision model still loading — first OCR may be slow."),
                );
            }
            return;
        }
    } else {
        stop_orphan_api_server(&state);
    }

    set_startup(
        &state,
        "ollama",
        "Starting Ollama…",
        false,
        25,
        None,
    );

    let ollama_port = resolve_ollama_port(&handle, &state);
    if !ollama_port_has_required_models(ollama_port)
        && !wait_http_ok(&ollama_tags_url(ollama_port), 4)
    {
        if let Some(child) = spawn_ollama_on_port(&handle, ollama_port) {
            *state.ollama.lock().unwrap() = Some(child);
        }
        let _ = wait_http_ok(&ollama_tags_url(ollama_port), 20);
    }

    set_startup(
        &state,
        "api",
        "Starting engine…",
        false,
        40,
        None,
    );

    let api_exe = resolve_resource_bin(&handle, "binaries/api-server/api-server.exe");
    if api_exe.is_none() {
        let hint = std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(|d| d.display().to_string()))
            .unwrap_or_else(|| "install folder".into());
        set_startup(
            &state,
            "error",
            "API server not found in app bundle.",
            true,
            0,
            Some(&format!(
                "Expected binaries/api-server/api-server.exe next to the app ({hint}). Re-run FormOCR-Setup.cmd."
            )),
        );
        return;
    }

    if let Some(child) = spawn_api(&handle, port, ollama_port) {
        *state.api.lock().unwrap() = Some(child);
        *state.api_log_path.lock().unwrap() = Some(api_log_path());
    } else {
        let log = api_log_path().display().to_string();
        set_startup(
            &state,
            "error",
            "Could not start FormOCR engine.",
            true,
            0,
            Some(&format!(
                "api-server failed to launch. Re-run FormOCR-Setup.cmd. Log: {log}"
            )),
        );
        return;
    }

    // Brief pause to let the process start and potentially fail fast.
    thread::sleep(Duration::from_millis(800));
    {
        let mut guard = state.api.lock().unwrap();
        if let Some(ref mut child) = *guard {
            if let Ok(Some(status)) = child.try_wait() {
                let log_hint = read_api_log_tail(5);
                let log_path = api_log_path().display().to_string();
                set_startup(
                    &state,
                    "error",
                    "FormOCR engine crashed on startup.",
                    true,
                    0,
                    Some(&format!(
                        "api-server.exe exited immediately (code {:?}). \
                         Likely cause: antivirus blocking, missing Visual C++ runtime, or wrong install. \
                         Re-run FormOCR-Setup.cmd.\nLog ({log_path}):\n{log_hint}",
                        status.code()
                    )),
                );
                return;
            }
        }
    }

    set_startup(
        &state,
        "vision",
        "Loading vision model…",
        false,
        55,
        None,
    );

    if let Some(h) = wait_for_api_ready_with_child(port, 240, Some(&state.api)) {
        if h.ocr_ready {
            let msg = if h.ollama_on_gpu == Some(true) {
                format!("Ready — GPU ({} MB)", h.ollama_vram_mb.unwrap_or(0))
            } else if h.ollama_on_gpu == Some(false) {
                "Ready — CPU mode".to_string()
            } else {
                "Ready".to_string()
            };
            set_startup(&state, "ready", &msg, true, 100, None);
        } else {
            set_startup(
                &state,
                "vision",
                "Loading vision model…",
                false,
                80,
                None,
            );
            if wait_for_api_ready(port, 180).is_some_and(|x| x.ocr_ready) {
                set_startup(&state, "ready", "Ready", true, 100, None);
            } else {
                set_startup(
                    &state,
                    "ready",
                    "Ready",
                    true,
                    90,
                    Some("Vision model did not finish loading. Restart FormOCR and wait."),
                );
            }
        }
    } else {
        set_startup(
            &state,
            "error",
            "Engine did not respond.",
            true,
            0,
            Some("api-server failed health check. Re-run FormOCR-Setup.cmd."),
        );
    }
}

#[tauri::command]
fn get_api_base_url(state: tauri::State<SidecarState>) -> String {
    let port = *state.api_port.lock().unwrap();
    format!("http://127.0.0.1:{port}")
}

#[tauri::command]
fn get_api_log_path(state: tauri::State<SidecarState>) -> String {
    state
        .api_log_path
        .lock()
        .unwrap()
        .as_ref()
        .map(|p| p.display().to_string())
        .unwrap_or_else(|| api_log_path().display().to_string())
}

#[tauri::command]
fn get_api_log_tail() -> String {
    read_api_log_tail(40)
}

#[tauri::command]
fn get_startup_status(state: tauri::State<SidecarState>) -> StartupStatus {
    state.startup.lock().unwrap().clone()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let sidecar_state = SidecarState {
        ollama: Mutex::new(None),
        api: Mutex::new(None),
        api_port: Mutex::new(8765),
        managed_ollama_port: Mutex::new(None),
        startup: Mutex::new(StartupStatus::default()),
        api_log_path: Mutex::new(None),
    };

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .manage(sidecar_state)
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                #[cfg(windows)]
                sync_window_chrome(&window);
                #[cfg(not(windows))]
                {
                    let _ = window.set_theme(Some(Theme::Dark));
                    let _ = window.set_background_color(Some(WINDOW_BG));
                }
            }

            let handle = app.handle().clone();
            let state = app.state::<SidecarState>();

            if let Some(port) = parse_dev_api_port() {
                *state.api_port.lock().unwrap() = port;
                set_startup(
                    &state,
                    "ready",
                    "Development mode — using external API.",
                    true,
                    100,
                    None,
                );
            } else {
                let port = read_api_port();
                *state.api_port.lock().unwrap() = port;
                set_startup(
                    &state,
                    "init",
                    "Starting…",
                    false,
                    0,
                    None,
                );
                thread::spawn(move || bootstrap_production(handle));
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_api_base_url, get_startup_status, get_api_log_path, get_api_log_tail])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                if let Some(state) = window.app_handle().try_state::<SidecarState>() {
                    stop_sidecars(&state);
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            if let Some(state) = app_handle.try_state::<SidecarState>() {
                stop_sidecars(&state);
            }
        }
    });
}
