// Local host tools for the isolated recompile. No guest code is replaced.
#pragma once
#include <atomic>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <rex/cvar.h>
#include <rex/input/mnk/mnk_input_driver.h>
#include <rex/logging.h>
#include <rex/rex_app.h>
#include <rex/runtime.h>
#include <rex/system/interfaces/graphics.h>
#include <rex/ui/keybinds.h>
#include <rex/ui/presenter.h>
#include <sstream>
#include <thread>
#if XBOX_NATIVE_HALO
#include "rex_animation.h"
#include "rex_menu_bridge.h"
#endif
#include "rex_controls.h"
#if XBOX_NATIVE_MULTIPLAYER
#include "rex_multiplayer.h"
#endif

class XboxNativeApp : public rex::ReXApp {
public:
  using rex::ReXApp::ReXApp;

protected:
#if XBOX_NATIVE_MULTIPLAYER
  void OnPreSetup(rex::RuntimeConfig&) override {
    XboxNativeInstallNetworkRegistry();
  }
#endif
  void OnPostSetup() override {
    if (window() && imgui_drawer())
      controls_ = std::make_unique<NativeControls>(
          runtime(), window(), imgui_drawer(), user_data_root());
#if XBOX_NATIVE_MULTIPLAYER
    XboxNativeMultiplayerSetup(runtime(), user_data_root());
#endif
    rex::input::mnk::SetMouseLookActive(false);
    REXLOG_INFO("[xbox-native] PC controls ready: F2 settings, Escape pause, "
                "F6 mouse look; guest menu mouse bridge enabled.");
    for (auto name :
         {"mnk_mode", "mnk_mouse", "mnk_sensitivity", "occlusion_query_enable",
          "query_occlusion_fake_sample_count", "render_target_path"}) {
      REXLOG_INFO("[xbox-native] {}={}", name, rex::cvar::GetFlagByName(name));
    }
    rex::ui::RegisterBind("bind_native_mouse", "F6",
                          "Release/capture mouse look", [] {
                            bool active = !rex::input::mnk::IsMouseLookActive();
                            rex::input::mnk::SetMouseLookActive(active);
                            REXLOG_INFO("[xbox-native] Mouse look {}",
                                        active ? "enabled" : "released");
                          });
    rex::ui::RegisterBind("bind_native_capture", "F8",
                          "Capture guest GPU output",
                          [this] { capture_requested_.store(true); });
    capture_worker_ = std::jthread([this](std::stop_token stop) {
      auto directory = user_data_root() / "captures";
      std::error_code ec;
      std::filesystem::create_directories(directory, ec);
      if (ec)
        return;
      auto request = directory / "capture.request";
      while (!stop.stop_requested()) {
#if XBOX_NATIVE_HALO
        if (rex::cvar::GetFlagByName("native_input_probe") == "true") {
          auto command = directory / "input.request";
          if (std::filesystem::exists(command, ec)) {
            std::ifstream file(command);
            std::string text;
            std::getline(file, text);
            file.close();
            std::filesystem::remove(command, ec);
            std::istringstream input(text);
            std::string name;
            input >> name;
            if (name == "buttons" && controls_) {
              unsigned buttons = 0;
              input >> std::hex >> buttons;
              controls_->ProbeButtons(uint16_t(buttons));
            } else if (name == "aa" && controls_) {
              int mode = -1;
              input >> mode;
              controls_->ProbeAntialiasing(mode);
            } else if (name == "interpolation") {
              int enabled = 1;
              input >> enabled;
              rex::cvar::SetFlagByName("native_interpolate_animations",
                                       enabled ? "true" : "false");
            } else if (name == "trace") {
              XboxNativeAnimationResetTrace();
            } else if (name == "move" && controls_) {
              int x = 0, y = 0;
              input >> x >> y;
              controls_->ProbeMove(int16_t(std::clamp(x, -32767, 32767)),
                                   int16_t(std::clamp(y, -32767, 32767)));
            } else if (name == "sprint") {
              int held = 0;
              input >> held;
              XboxNativeSprintHeld(held != 0);
            } else if (name == "key" && controls_) {
              unsigned code = 0;
              int down = 0;
              input >> code >> down;
              controls_->ProbeKey(code, down != 0);
            } else if (name == "mouse") {
              unsigned type = 0, w = 1152, h = 648;
              float x = 0, y = 0;
              input >> type >> x >> y >> w >> h;
              XboxNativeMenuMouse(type, x, y, w, h);
            } else if (name == "look") {
              float dx = 0, dy = 0;
              input >> dx >> dy;
              rex::input::mnk::SetMouseLookActive(true);
              XboxNativeMouseMotion(dx, dy);
            } else if (name == "release") {
              rex::input::mnk::SetMouseLookActive(false);
              XboxNativeMouseReset();
            } else if (name == "map") {
              std::string map;
              input >> map;
              REXLOG_INFO("[native-probe] Direct map {} accepted={}",
                          map, XboxNativeQueueMap(map));
            } else if (name == "gpu_flag") {
              std::string flag, value;
              input >> flag >> value;
              // Diagnostic-only, bounded whitelist; never accept arbitrary
              // runtime settings or filesystem destinations from this file.
              bool allowed = flag == "readback_resolve" ||
                             flag == "readback_memexport" ||
                             flag == "readback_memexport_fast" ||
                             flag == "gpu_allow_invalid_fetch_constants" ||
                             flag == "clear_memory_page_state" ||
                             flag == "pre_mask_resolve_l2_block" ||
                             flag == "native_querybatch_range" ||
                             flag == "query_occlusion_fake_sample_count" ||
                             flag == "occlusion_query_enable";
              if (allowed)
                REXLOG_INFO("[native-probe] GPU flag {}={} accepted={}",
                            flag, value, rex::cvar::SetFlagByName(flag, value));
            }
            REXLOG_INFO("[native-probe] Command: {}", text);
          }
        }
#endif
        bool requested = capture_requested_.exchange(false);
        if (std::filesystem::exists(request, ec)) {
          std::filesystem::remove(request, ec);
          requested = true;
        }
        if (requested)
          CaptureFrame(directory);
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
      }
    });
  }
  void OnShutdown() override {
#if XBOX_NATIVE_MULTIPLAYER
    XboxNativeMultiplayerShutdown();
#endif
    controls_.reset();
    rex::ui::UnregisterBind("bind_native_capture");
    rex::ui::UnregisterBind("bind_native_mouse");
    capture_worker_.request_stop();
    if (capture_worker_.joinable())
      capture_worker_.join();
  }

private:
  void CaptureFrame(const std::filesystem::path &directory) {
    auto *graphics = runtime()->graphics_system();
    auto *presenter = graphics ? graphics->presenter() : nullptr;
    rex::ui::RawImage frame;
    if (!presenter || !presenter->CaptureGuestOutput(frame) || !frame.width ||
        !frame.height) {
      REXLOG_WARN("[xbox-native] No guest frame available for capture");
      return;
    }
    // Portable RGB pixmap: tightly packed RGB, independent of GPU row pitch.
    if (frame.stride < size_t(frame.width) * 4 ||
        frame.data.size() <
            size_t(frame.height - 1) * frame.stride + size_t(frame.width) * 4)
      return;
    auto stamp = std::chrono::system_clock::now().time_since_epoch().count();
    auto path = directory / ("frame-" + std::to_string(stamp) + ".ppm");
    std::ofstream file(path, std::ios::binary);
    file << "P6\n" << frame.width << ' ' << frame.height << "\n255\n";
    for (uint32_t y = 0; y < frame.height; ++y) {
      auto *row = frame.data.data() + size_t(y) * frame.stride;
      for (uint32_t x = 0; x < frame.width; ++x)
        file.write(reinterpret_cast<char *>(row + x * 4), 3);
    }
    if (file)
      REXLOG_INFO("[xbox-native] Guest GPU capture {} ({}x{})", path.string(),
                  frame.width, frame.height);
  }
  std::atomic<bool> capture_requested_{false};
  std::jthread capture_worker_;
  std::unique_ptr<NativeControls> controls_;
};
