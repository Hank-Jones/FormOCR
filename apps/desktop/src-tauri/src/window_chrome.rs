//! Native window chrome theming (Windows title bar).

/// App `--bg` token: #070b12
const BG_BGR: u32 = 0x0012_0b07;
/// App `--text` token: #f1f5f9
const TEXT_BGR: u32 = 0x00f9_f5f1;

#[cfg(windows)]
pub fn apply(hwnd_raw: isize) {
    use windows_sys::Win32::Foundation::HWND;
    use windows_sys::Win32::Graphics::Dwm::{
        DwmSetWindowAttribute, DWMWA_BORDER_COLOR, DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR,
        DWMWA_USE_IMMERSIVE_DARK_MODE,
    };

    let hwnd = hwnd_raw as HWND;

    unsafe {
        let dark: i32 = 1;
        let _ = DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE as u32,
            &dark as *const _ as *const _,
            std::mem::size_of::<i32>() as u32,
        );

        for (attr, color) in [
            (DWMWA_CAPTION_COLOR, BG_BGR),
            (DWMWA_BORDER_COLOR, BG_BGR),
            (DWMWA_TEXT_COLOR, TEXT_BGR),
        ] {
            let _ = DwmSetWindowAttribute(
                hwnd,
                attr as u32,
                &color as *const _ as *const _,
                std::mem::size_of::<u32>() as u32,
            );
        }
    }
}
