fn main() {
    let icons = std::path::Path::new("icons");
    for name in [
        "icon.ico",
        "icon.png",
        "32x32.png",
        "128x128.png",
        "128x128@2x.png",
    ] {
        let path = icons.join(name);
        if path.exists() {
            println!("cargo:rerun-if-changed={}", path.display());
        }
    }
    let app_icon = std::path::Path::new("app-icon.png");
    if app_icon.exists() {
        println!("cargo:rerun-if-changed={}", app_icon.display());
    }
    tauri_build::build()
}
