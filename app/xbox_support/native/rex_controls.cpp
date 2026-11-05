#include "rex_controls.h"
#include "rex_rt_api.h"
#if XBOX_NATIVE_MULTIPLAYER
#include "rex_multiplayer.h"
#endif
#if XBOX_NATIVE_HALO
#include "rex_menu_bridge.h"
#else
static void XboxNativeMenuEnabled(bool) {}
static void XboxNativeMenuMouse(uint32_t, float, float, uint32_t, uint32_t,
                                uint32_t, float) {}
static void XboxNativeMouseReset() {}
static void XboxNativeMouseMotion(float, float) {}
static void XboxNativeSprintHeld(bool) {}
static bool XboxNativeRequestSkip() { return false; }
#endif
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <imgui.h>
#include <iomanip>
#include <map>
#include <mutex>
#include <rex/cvar.h>
#include <rex/filesystem.h>
#include <rex/input/input_driver.h>
#include <rex/input/input_system.h>
#include <rex/input/mnk/mnk_input_driver.h>
#include <rex/logging.h>
#include <rex/platform/dynlib.h>
#include <rex/runtime.h>
#include <rex/ui/imgui_dialog.h>
#include <rex/ui/keybinds.h>
#include <rex/ui/window.h>
#include <rex/ui/window_sdl.h>
#include <set>
#include <sstream>
#include <string>
#include <toml++/toml.hpp>
#include <vector>

REXCVAR_DEFINE_BOOL(
    native_input_probe, false, "Local tests",
    "Enable opt-in local input test commands and guest FPS logging");
REXCVAR_DEFINE_BOOL(native_unlock_fps, true, "PC",
                    "Remove Halo's 30 FPS presentation limit");

namespace {
using namespace rex;
using namespace rex::input;
using Clock = std::chrono::steady_clock;
using VK = rex::ui::VirtualKey;
struct Binding {
  const char *flag;
  const char *label;
  const char *initial;
};
constexpr Binding bindings[] = {
    {"keybind_lstick_up", "Avancer", "W"},
    {"keybind_lstick_down", "Reculer", "S"},
    {"keybind_lstick_left", "Gauche", "A"},
    {"keybind_lstick_right", "Droite", "D"},
    {"keybind_a", "Sauter / Valider", "Space"},
    {"keybind_b", "Melee / Retour", "F,Backspace"},
    {"keybind_x", "Action / Recharger", "R,E"},
    {"keybind_y", "Changer d'arme", "Q"},
    {"keybind_right_trigger", "Tirer", "LMB"},
    {"keybind_rstick_press", "Zoomer", "RMB"},
    {"keybind_left_trigger", "Grenade", "G"},
    {"keybind_lstick_press", "S'accroupir", "C"},
    {"keybind_left_shoulder", "Bouton LB", "1"},
    {"keybind_right_shoulder", "Bouton RB", "3"},
    {"keybind_back", "Objectifs / Retour", "Tab"},
    {"keybind_start", "Pause (Echap reste actif)", "Return"},
    {"keybind_dpad_up", "Menu haut", "Up"},
    {"keybind_dpad_down", "Menu bas", "Down"},
    {"keybind_dpad_left", "Menu gauche", "Left"},
    {"keybind_dpad_right", "Menu droite", "Right"},
};
struct State {
  std::atomic<bool> panel{false}, focus{true}, overlay_capture{false};
  std::atomic<int64_t> pause_until{0};
  std::atomic<uint16_t> probe_buttons{0};
  std::atomic<int> probe_aa{-1};
  std::atomic<int16_t> probe_x{0}, probe_y{0};
  bool show_fps = true, resume_capture = false, paused_for_panel = false,
       azerty = true;
  bool escape_paused = false, escape_capture = false;
  int rebinding = -1;
  int antialiasing = 3;
  bool ray_tracing = false;
  bool ray_debug = false, ray_ao = true, ray_reflections = true, ray_gi = true;
  float ray_intensity = .35f, ray_radius = 1.5f;
  float fps = 0;
  std::string message;
  std::filesystem::path config;
  struct RuntimeBinding {
    std::string original, expanded;
  };
  std::map<std::string, RuntimeBinding> sprint_bindings;
  std::string BindingValue(const char *flag) const {
    auto value = rex::cvar::GetFlagByName(flag);
    auto it = sprint_bindings.find(flag);
    return it != sprint_bindings.end() && value == it->second.expanded
               ? it->second.original
               : value;
  }
  void ApplySprintBindings() {
    std::map<std::string, std::string> originals;
    std::set<std::string> explicit_chords;
    auto tokens = [](const std::string &text) {
      std::vector<std::string> out;
      std::istringstream input(text);
      std::string token;
      while (std::getline(input, token, ',')) {
        auto first = token.find_first_not_of(' '),
             last = token.find_last_not_of(' ');
        if (first != std::string::npos)
          out.push_back(token.substr(first, last - first + 1));
      }
      return out;
    };
    for (auto &b : bindings) {
      auto value = BindingValue(b.flag);
      originals[b.flag] = value;
      for (auto &token : tokens(value))
        if (token.find('+') != std::string::npos)
          explicit_chords.insert(token);
    }
    bool sprint = rex::cvar::GetFlagByName("native_sprint") == "true";
    for (auto &b : bindings) {
      auto value = originals[b.flag], expanded = value;
      if (sprint)
        for (auto &token : tokens(value)) {
          if (token.find('+') == std::string::npos && token != "Shift" &&
              token != "Control" && token != "Alt") {
            auto chord = "Shift+" + token;
            if (!explicit_chords.contains(chord))
              expanded += (expanded.empty() ? "" : ",") + chord;
          }
        }
      sprint_bindings[b.flag] = {value, expanded};
      rex::cvar::SetFlagByName(b.flag, expanded);
    }
  }
  void SprintKey(VK key, bool down) {
    if (key == VK::kShift || key == VK::kLShift || key == VK::kRShift)
      XboxNativeSprintHeld(down && focus.load() && !panel.load() &&
                           rex::input::mnk::IsMouseLookActive());
  }
  void PausePulse() {
    pause_until.store(std::chrono::duration_cast<std::chrono::milliseconds>(
                          Clock::now().time_since_epoch())
                          .count() +
                      100);
  }
  void Escape() {
    if (rebinding >= 0) {
      rebinding = -1;
      return;
    }
    if (panel.load()) {
      TogglePanel();
      return;
    }
    PausePulse();
    if (!escape_paused) {
      escape_capture = rex::input::mnk::IsMouseLookActive();
      rex::input::mnk::SetMouseLookActive(false);
      XboxNativeMouseReset();
    } else
      rex::input::mnk::SetMouseLookActive(escape_capture);
    escape_paused = !escape_paused;
  }
  void Save() {
    try {
      std::filesystem::create_directories(config.parent_path());
      auto temporary = config;
      temporary += ".tmp";
      std::ofstream file(temporary, std::ios::trunc);
      file << "input_version = 2\n"
           << "show_fps = " << (show_fps ? "true" : "false")
           << "\nazerty = " << (azerty ? "true" : "false")
           << "\nunlock_fps = " << rex::cvar::GetFlagByName("native_unlock_fps")
           << "\nantialiasing = " << antialiasing
           << "\nray_tracing = " << (ray_tracing ? "true" : "false")
           << "\nray_debug = " << (ray_debug ? "true" : "false")
           << "\nray_ao = " << (ray_ao ? "true" : "false")
           << "\nray_reflections = " << (ray_reflections ? "true" : "false")
           << "\nray_gi = " << (ray_gi ? "true" : "false")
           << "\nray_intensity = " << ray_intensity
           << "\nray_radius = " << ray_radius << "\ninterpolate_animations = "
           << rex::cvar::GetFlagByName("native_interpolate_animations")
           << "\ninterpolate_cinematics = "
           << rex::cvar::GetFlagByName("native_interpolate_cinematics")
           << "\ninterpolate_vehicles = "
           << rex::cvar::GetFlagByName("native_interpolate_vehicles")
           << "\nfullscreen = " << rex::cvar::GetFlagByName("fullscreen")
           << "\nfill_screen = "
           << (rex::cvar::GetFlagByName("present_letterbox") == "false"
                   ? "true"
                   : "false")
           << "\nsprint_weapon_animation = "
           << rex::cvar::GetFlagByName("native_sprint_weapon_animation")
           << "\nsprint = " << rex::cvar::GetFlagByName("native_sprint")
           << "\nsprint_multiplier = "
           << rex::cvar::GetFlagByName("native_sprint_multiplier")
           << "\nbiped_physics_hz = "
           << rex::cvar::GetFlagByName("native_biped_physics_hz")
           << "\nsensitivity = " << rex::cvar::GetFlagByName("mnk_sensitivity")
           << "\n[bindings]\n";
      for (auto &binding : bindings)
        file << binding.flag << " = " << std::quoted(BindingValue(binding.flag))
             << '\n';
      file.close();
      if (!file)
        throw std::runtime_error("Ecriture impossible");
      std::filesystem::rename(temporary, config);
      message = "Reglages enregistres";
    } catch (const std::exception &e) {
      message = std::string("Erreur : ") + e.what();
    }
  }
  void Load() {
    if (!std::filesystem::exists(config)) {
      ApplySprintBindings();
      return;
    }
    try {
      auto table = toml::parse_file(config.string());
      show_fps = table["show_fps"].value_or(true);
      azerty = table["azerty"].value_or(true);
      antialiasing = std::clamp(table["antialiasing"].value_or(3), 0, 3);
      ray_tracing = table["ray_tracing"].value_or(false);
      ray_debug = table["ray_debug"].value_or(false);
      ray_ao = table["ray_ao"].value_or(true);
      ray_reflections = table["ray_reflections"].value_or(true);
      ray_gi = table["ray_gi"].value_or(true);
      ray_intensity =
          std::clamp(table["ray_intensity"].value_or(.35f), 0.f, 1.f);
      ray_radius = std::clamp(table["ray_radius"].value_or(1.5f), .05f, 10.f);
      if (!std::isfinite(ray_intensity))
        ray_intensity = .35f;
      if (!std::isfinite(ray_radius))
        ray_radius = 1.5f;
      if (auto fullscreen = table["fullscreen"].value<bool>())
        rex::cvar::SetFlagByName("fullscreen", *fullscreen ? "true" : "false");
      if (auto fill = table["fill_screen"].value<bool>())
        rex::cvar::SetFlagByName("present_letterbox", *fill ? "false" : "true");
      rex::cvar::SetFlagByName(
          "native_interpolate_cinematics",
          table["interpolate_cinematics"].value_or(true) ? "true" : "false");
      rex::cvar::SetFlagByName(
          "native_interpolate_vehicles",
          table["interpolate_vehicles"].value_or(true) ? "true" : "false");
      rex::cvar::SetFlagByName(
          "native_sprint_weapon_animation",
          table["sprint_weapon_animation"].value_or(true) ? "true" : "false");
      rex::cvar::SetFlagByName(
          "native_interpolate_animations",
          table["interpolate_animations"].value_or(true) ? "true" : "false");
      rex::cvar::SetFlagByName(
          "native_sprint", table["sprint"].value_or(true) ? "true" : "false");
      double sprint = table["sprint_multiplier"].value_or(1.5);
      int hz = table["biped_physics_hz"].value_or(60);
      rex::cvar::SetFlagByName(
          "native_biped_physics_hz",
          std::to_string(hz == 30 || hz == 60 || hz == 120 ? hz : 60));
      if (std::isfinite(sprint))
        rex::cvar::SetFlagByName("native_sprint_multiplier",
                                 std::to_string(std::clamp(sprint, 1., 2.)));
      bool legacy_mouse = table["input_version"].value_or(0) < 2;
      double sensitivity =
          legacy_mouse ? 1.0 : table["sensitivity"].value_or(1.0);
      rex::cvar::SetFlagByName("native_unlock_fps",
                               table["unlock_fps"].value_or(true) ? "true"
                                                                  : "false");
      if (sensitivity >= 0.01 && sensitivity <= 10.0)
        rex::cvar::SetFlagByName("mnk_sensitivity",
                                 std::to_string(sensitivity));
      for (auto &binding : bindings)
        if (auto value = table["bindings"][binding.flag].value<std::string>())
          rex::cvar::SetFlagByName(binding.flag, *value);
      if (legacy_mouse) {
        auto backup = config;
        backup += ".analog.bak";
        if (!std::filesystem::exists(backup))
          std::filesystem::copy_file(config, backup);
        Save();
        message = "Visee directe activee ; ancienne sensibilite sauvegardee.";
      }
      ApplySprintBindings();
    } catch (const std::exception &e) {
      message = std::string("Lecture des reglages : ") + e.what();
    }
  }
  void TogglePanel() {
    if (!panel.load()) {
      resume_capture = rex::input::mnk::IsMouseLookActive();
      paused_for_panel = resume_capture;
      if (paused_for_panel)
        PausePulse();
      rex::input::mnk::SetMouseLookActive(false);
      XboxNativeMouseReset();
      panel.store(true);
      XboxNativeMenuEnabled(false);
    } else {
      panel.store(false);
      rebinding = -1;
      if (paused_for_panel)
        PausePulse();
      rex::input::mnk::SetMouseLookActive(resume_capture);
      paused_for_panel = false;
      XboxNativeMenuEnabled(true);
    }
  }
  void Bind(std::string name) {
    if (rebinding < 0 || name.empty())
      return;
    if (name == "F2" || name == "F6" || name == "F8" || name == "Escape") {
      message = "Cette touche est reservee (F2, F6, F8, Echap)";
      return;
    }
    rex::cvar::SetFlagByName(bindings[rebinding].flag, name);
    ApplySprintBindings();
    rebinding = -1;
    Save();
  }
};

// A separate synthetic pad supplies short Start presses, even while the
// settings panel has temporarily stopped the ordinary input drivers.
class PauseDriver final : public rex::input::InputDriver {
  std::shared_ptr<State> state_;

public:
  explicit PauseDriver(std::shared_ptr<State> state)
      : InputDriver(nullptr, 0), state_(std::move(state)) {}
  X_STATUS Setup() override { return X_STATUS_SUCCESS; }
  void EnumerateDevices(std::vector<rex::input::DeviceInfo> &out) override {
    rex::input::DeviceInfo d;
    d.id = static_cast<rex::input::DeviceId>(0x43595043);
    d.name = "PC shortcuts";
    d.synthetic = true;
    out.push_back(d);
  }
  X_RESULT GetDeviceCapabilities(rex::input::DeviceId, uint32_t,
                                 X_INPUT_CAPABILITIES *caps) override {
    if (caps) {
      *caps = {};
      caps->type = 1;
      caps->sub_type = 1;
      caps->gamepad.buttons = X_INPUT_GAMEPAD_START;
    }
    return X_ERROR_SUCCESS;
  }
  X_RESULT GetDeviceState(rex::input::DeviceId,
                          X_INPUT_STATE *result) override {
    if (!result)
      return X_ERROR_SUCCESS;
    *result = {};
    auto now = std::chrono::duration_cast<std::chrono::milliseconds>(
                   Clock::now().time_since_epoch())
                   .count();
    if (state_->focus.load() && now < state_->pause_until.load())
      result->gamepad.buttons = X_INPUT_GAMEPAD_START;
    result->gamepad.buttons =
        uint16_t(result->gamepad.buttons) | state_->probe_buttons.load();
#if XBOX_NATIVE_HALO
    result->gamepad.buttons = uint16_t(result->gamepad.buttons) |
                              XboxNativeBootButtons();
#endif
    result->gamepad.thumb_lx = state_->probe_x.load();
    result->gamepad.thumb_ly = state_->probe_y.load();
    result->packet_number = static_cast<uint32_t>(now);
    return X_ERROR_SUCCESS;
  }
  X_RESULT SetDeviceVibration(rex::input::DeviceId,
                              X_INPUT_VIBRATION *) override {
    return X_ERROR_SUCCESS;
  }
  X_RESULT GetDeviceKeystroke(rex::input::DeviceId, uint32_t,
                              X_INPUT_KEYSTROKE *) override {
    return X_ERROR_EMPTY;
  }
};

class ControlsDialog final : public rex::ui::ImGuiDialog {
  std::shared_ptr<State> state_;
  rex::platform::DynamicLibrary plugin_;
  using FrameCounter = uint64_t (*)();
  FrameCounter frames_ = nullptr;
  using SetAntialiasing = void (*)(int);
  SetAntialiasing set_aa_ = nullptr;
  using SetRayTracing = void (*)(int, float, float);
  using GetRtStatus = void (*)(NativeRtStatus *);
  using SetRtEffects = void (*)(uint32_t, float, float);
  SetRayTracing set_rt_ = nullptr;
  GetRtStatus rt_status_ = nullptr;
  SetRtEffects rt_effects_ = nullptr;
  uint32_t applied_effects_ = UINT32_MAX;
  int applied_rt_ = -1;
  float applied_intensity_ = -1, applied_radius_ = -1;
  int applied_aa_ = -1;
  uint64_t previous_frames_ = 0;
  Clock::time_point previous_time_ = Clock::now();

public:
  ControlsDialog(rex::ui::ImGuiDrawer *drawer, std::shared_ptr<State> state)
      : ImGuiDialog(drawer), state_(std::move(state)) {
    // Loading a second GPU backend registers duplicate CVars and drives an
    // inactive plugin. Only use extensions of the backend selected at startup.
    if (rex::cvar::GetFlagByName("gpu_plugin") != "xenos-occlusion")
      return;
    auto plugin =
        rex::filesystem::GetExecutableFolder() / "rexgpu-xenos-occlusion.dll";
    if (plugin_.Load(plugin)) {
      frames_ = plugin_.GetSymbol<FrameCounter>("rex_gpu_guest_frame_count");
      set_aa_ = plugin_.GetSymbol<SetAntialiasing>("rex_gpu_set_antialiasing");
      set_rt_ = plugin_.GetSymbol<SetRayTracing>("rex_gpu_set_raytracing");
      rt_status_ = plugin_.GetSymbol<GetRtStatus>("rex_gpu_get_rt_status");
      rt_effects_ = plugin_.GetSymbol<SetRtEffects>("rex_gpu_set_rt_effects");
      native_rt_projection.store(plugin_.GetSymbol<NativeRtSetProjection>(
          "rex_gpu_set_rt_projection"));
    }
  }
  void OnDraw(ImGuiIO &io) override {
    int rt_mode = state_->ray_tracing ? (state_->ray_debug ? 2 : 1) : 0;
#if XBOX_NATIVE_MULTIPLAYER
    if (XboxNativeLocalPlayers() > 1) rt_mode = 0;
#endif
    uint32_t effects = (state_->ray_ao ? 1u : 0u) |
                       (state_->ray_reflections ? 2u : 0u) |
                       (state_->ray_gi ? 4u : 0u);
    if (rt_effects_ && effects != applied_effects_) {
      rt_effects_(effects, .15f, .18f);
      applied_effects_ = effects;
    }
    if (set_rt_ && (applied_rt_ != rt_mode ||
                    applied_intensity_ != state_->ray_intensity ||
                    applied_radius_ != state_->ray_radius)) {
      set_rt_(rt_mode, state_->ray_intensity, state_->ray_radius);
      applied_rt_ = rt_mode;
      applied_intensity_ = state_->ray_intensity;
      applied_radius_ = state_->ray_radius;
    }
    int requested_aa = state_->probe_aa.exchange(-1);
    if (requested_aa >= 0 && requested_aa <= 3)
      state_->antialiasing = requested_aa;
    if (set_aa_ && applied_aa_ != state_->antialiasing) {
      set_aa_(state_->antialiasing);
      applied_aa_ = state_->antialiasing;
      REXLOG_INFO("[xbox-native] Antialiasing mode {} (0=off, 1=FXAA, 2=FXAA "
                  "strong, 3=SMAA native)",
                  applied_aa_);
    }
    state_->overlay_capture.store(io.WantCaptureMouse ||
                                  io.WantCaptureKeyboard);
    auto now = Clock::now();
    float elapsed = std::chrono::duration<float>(now - previous_time_).count();
    if (elapsed >= 0.5f) {
      uint64_t frames = frames_ ? frames_() : 0;
      state_->fps = frames_ ? float(frames - previous_frames_) / elapsed : 0;
      if (rex::cvar::GetFlagByName("native_input_probe") == "true")
        REXLOG_INFO("[native-probe] {:.2f} guest FPS, swaps {}", state_->fps,
                    frames);
      previous_frames_ = frames;
      previous_time_ = now;
    }
    NativeRtStatus rt_status{};
    if (rt_status_)
      rt_status_(&rt_status);
    if (state_->show_fps || set_rt_) {
      ImGui::SetNextWindowPos(ImVec2(io.DisplaySize.x - 12, 12),
                              ImGuiCond_Always, ImVec2(1, 0));
      ImGui::SetNextWindowBgAlpha(0.65f);
      ImGui::Begin(
          "##native_fps", nullptr,
          ImGuiWindowFlags_AlwaysAutoResize | ImGuiWindowFlags_NoDecoration |
              ImGuiWindowFlags_NoInputs | ImGuiWindowFlags_NoFocusOnAppearing |
              ImGuiWindowFlags_NoNav);
      if (state_->show_fps && frames_)
        ImGui::Text("%.1f FPS", state_->fps);
      else if (state_->show_fps)
        ImGui::TextUnformatted("FPS : indisponible");
      if (set_rt_) {
        const char *label = state_->ray_tracing && !rt_mode ? "RT suspendu (coop)"
                            : !state_->ray_tracing  ? "RT OFF [F3]"
                            : rt_status.state < 0 ? "RT : ERREUR [F3]"
                            : rt_status.state == 2 && rt_status.draws
                                ? "RT ACTIF [F3]"
                                : "RT : ATTENTE 3D [F3]";
        ImGui::TextColored(rt_mode && rt_status.state == 2 &&
                                   rt_status.draws
                               ? ImVec4(.3f, 1, .4f, 1)
                               : ImVec4(1, .75f, .3f, 1),
                           "%s", label);
      }
      ImGui::End();
    }
    if (!rex::input::mnk::IsMouseLookActive() && !state_->panel.load()) {
      ImGui::SetNextWindowPos(ImVec2(12, 12), ImGuiCond_Always);
      ImGui::Begin(
          "##native_toolbar", nullptr,
          ImGuiWindowFlags_AlwaysAutoResize | ImGuiWindowFlags_NoDecoration |
              ImGuiWindowFlags_NoFocusOnAppearing | ImGuiWindowFlags_NoNav);
      if (ImGui::Button("Clavier / souris  [F2]"))
        state_->TogglePanel();
      ImGui::End();
    }
    DrawPanel(state_, io, set_rt_ != nullptr, rt_status);
  }
  static void DrawPanel(std::shared_ptr<State> state_, ImGuiIO &io,
                        bool has_rt = false, NativeRtStatus rt_status = {}) {
    if (!state_->panel.load())
      return;
    ImGui::SetNextWindowPos(
        ImVec2(io.DisplaySize.x * .5f, io.DisplaySize.y * .5f),
        ImGuiCond_Appearing, ImVec2(.5f, .5f));
    ImGui::SetNextWindowSize(
        ImVec2(620, std::min(880.0f, io.DisplaySize.y - 35)),
        ImGuiCond_Appearing);
    bool open = true;
    if (ImGui::Begin("Clavier et souris##native_controls", &open,
                     ImGuiWindowFlags_NoCollapse)) {
      ImGui::TextUnformatted(
          "Echap : pause / retour. F6 : capturer ou liberer la souris.");
      ImGui::TextDisabled(
          "Version PC 2026-10-21.1 : rendu Anniversary");
      ImGui::TextDisabled(
          "Visee directe : sans zone morte ni acceleration de stick.");
      float sensitivity =
          std::stof(rex::cvar::GetFlagByName("mnk_sensitivity"));
      if (ImGui::SliderFloat("Sensibilite souris", &sensitivity, .05f, 5.f,
                             "%.2f"))
        rex::cvar::SetFlagByName("mnk_sensitivity",
                                 std::to_string(sensitivity));
      ImGui::Checkbox("Afficher les FPS", &state_->show_fps);
      ImGui::SameLine();
      ImGui::Checkbox("Noms AZERTY", &state_->azerty);
      bool fullscreen = rex::cvar::GetFlagByName("fullscreen") == "true";
      if (ImGui::Checkbox("Plein ecran", &fullscreen))
        rex::cvar::SetFlagByName("fullscreen", fullscreen ? "true" : "false");
      bool fill = rex::cvar::GetFlagByName("present_letterbox") == "false";
      if (ImGui::Checkbox("Remplir l'ecran (etirement)", &fill))
        rex::cvar::SetFlagByName("present_letterbox", fill ? "false" : "true");
      bool unlock = rex::cvar::GetFlagByName("native_unlock_fps") == "true";
      if (ImGui::Checkbox("Debloquer la limite de 30 FPS", &unlock))
        rex::cvar::SetFlagByName("native_unlock_fps",
                                 unlock ? "true" : "false");
      ImGui::Combo("Anti-aliasing", &state_->antialiasing,
                   "Desactive\0FXAA\0FXAA fort\0SMAA 1x High (natif)\0");
      ImGui::BeginDisabled(!has_rt);
      ImGui::Checkbox("Ray tracing natif DXR (F3)", &state_->ray_tracing);
      if (state_->ray_tracing) {
        ImGui::Checkbox("Occlusion ambiante RT", &state_->ray_ao);
        ImGui::Checkbox("Reflets RT (experimentaux)", &state_->ray_reflections);
        ImGui::Checkbox("Rebonds RT (couleur des materiaux)", &state_->ray_gi);
        ImGui::TextDisabled("Materiaux alpha/HDR ; denoising spatial en 2 passes");
        ImGui::Checkbox("Visualiser la geometrie RT", &state_->ray_debug);
        ImGui::SliderFloat("Intensite RT", &state_->ray_intensity, 0.f, 1.f,
                           "%.2f");
        ImGui::SliderFloat("Portee RT", &state_->ray_radius, .05f, 5.f, "%.2f");
        if (rt_status.state == 2)
          ImGui::TextDisabled("DXR actif : %u passes 3D capturees",
                              rt_status.draws);
        else if (rt_status.state == -1)
          ImGui::TextDisabled("DXR 1.1 non disponible sur cette carte.");
        else if (rt_status.state == -2)
          ImGui::TextDisabled(
              "Initialisation DXR impossible ; rendu classique conserve.");
        else if (rt_status.state == -3)
          ImGui::TextDisabled(
              "Capture 3D refusee : consulter le journal native-rt.");
        else
          ImGui::TextDisabled("En attente de la geometrie 3D ; premiere "
                              "activation plus lente.");
      }
      ImGui::EndDisabled();
      bool interpolation =
          rex::cvar::GetFlagByName("native_interpolate_animations") == "true";
      if (ImGui::Checkbox("Interpolation des animations", &interpolation))
        rex::cvar::SetFlagByName("native_interpolate_animations",
                                 interpolation ? "true" : "false");
      bool cinematic =
          rex::cvar::GetFlagByName("native_interpolate_cinematics") == "true";
      if (ImGui::Checkbox("Interpolation des cameras de cinematiques",
                          &cinematic))
        rex::cvar::SetFlagByName("native_interpolate_cinematics",
                                 cinematic ? "true" : "false");
      bool vehicles =
          rex::cvar::GetFlagByName("native_interpolate_vehicles") == "true";
      if (ImGui::Checkbox("Interpolation vehicules et camera de suivi",
                          &vehicles))
        rex::cvar::SetFlagByName("native_interpolate_vehicles",
                                 vehicles ? "true" : "false");
      bool weapon_bob =
          rex::cvar::GetFlagByName("native_sprint_weapon_animation") == "true";
      if (ImGui::Checkbox("Balancement de l'arme pendant la course",
                          &weapon_bob))
        rex::cvar::SetFlagByName("native_sprint_weapon_animation",
                                 weapon_bob ? "true" : "false");
      bool sprint = rex::cvar::GetFlagByName("native_sprint") == "true";
      if (ImGui::Checkbox("Courir avec Maj (maintenir, a pied)", &sprint)) {
        rex::cvar::SetFlagByName("native_sprint", sprint ? "true" : "false");
        XboxNativeSprintHeld(false);
        state_->ApplySprintBindings();
      }
      float speed =
          std::stof(rex::cvar::GetFlagByName("native_sprint_multiplier"));
      if (ImGui::SliderFloat("Vitesse de course", &speed, 1.f, 2.f, "x%.2f"))
        rex::cvar::SetFlagByName("native_sprint_multiplier",
                                 std::to_string(speed));
      ImGui::TextDisabled(
          "ReShade : touche Home pour ses effets, si installe.");
      ImGui::TextDisabled("Cliquez une touche, puis appuyez sur sa nouvelle "
                          "touche ou un clic.");
      int hz = std::stoi(rex::cvar::GetFlagByName("native_biped_physics_hz"));
      int physics = hz == 120 ? 2 : hz == 60 ? 1 : 0;
      if (ImGui::Combo("Physique personnages", &physics,
                       "30 Hz (origine)\0Sous-pas 60 Hz\0Sous-pas 120 Hz\0"))
        rex::cvar::SetFlagByName("native_biped_physics_hz",
                                 std::to_string(physics == 2   ? 120
                                                : physics == 1 ? 60
                                                               : 30));
      ImGui::TextDisabled(
          "Sous-pas de collisions ; logique IA et scripts : 30 Hz.");
#if XBOX_NATIVE_MULTIPLAYER
      XboxNativeMultiplayerPanel();
#endif
      ImGui::BeginChild("bindings", ImVec2(0, -70), true);
      for (int i = 0; i < int(std::size(bindings)); ++i) {
        ImGui::PushID(i);
        ImGui::TextUnformatted(bindings[i].label);
        ImGui::SameLine(260);
        std::string value = state_->BindingValue(bindings[i].flag);
        if (state_->azerty) {
          if (value == "W")
            value = "Z";
          else if (value == "A")
            value = "Q";
          else if (value == "Q")
            value = "A";
          else if (value == "Z")
            value = "W";
        }
        if (state_->rebinding == i)
          value = "Appuyez... (Echap : annuler)";
        if (ImGui::Button(value.empty() ? "Non assigne" : value.c_str(),
                          ImVec2(-1, 0)))
          state_->rebinding = i;
        ImGui::PopID();
      }
      ImGui::EndChild();
      if (ImGui::Button("Enregistrer"))
        state_->Save();
      ImGui::SameLine();
      if (ImGui::Button("Valeurs par defaut")) {
        for (auto &b : bindings)
          rex::cvar::SetFlagByName(b.flag, b.initial);
        rex::cvar::SetFlagByName("mnk_sensitivity", "1.0");
        state_->ApplySprintBindings();
        state_->Save();
      }
      ImGui::SameLine();
      if (ImGui::Button("Fermer"))
        open = false;
      ImGui::TextUnformatted(state_->message.c_str());
    }
    ImGui::End();
    if (!open)
      state_->TogglePanel();
  }
};
} // namespace

struct NativeControls::Impl : rex::ui::WindowInputListener,
                              rex::ui::WindowListener {
  rex::ui::Window *window;
  rex::ui::ImGuiDrawer *drawer;
  std::shared_ptr<State> state = std::make_shared<State>();
  std::unique_ptr<ControlsDialog> dialog;
  struct MenuListener : rex::ui::WindowInputListener {
    Impl *owner;
    explicit MenuListener(Impl *value) : owner(value) {}
    void OnMouseMove(rex::ui::MouseEvent &e) override {
      owner->MenuMouse(e, 1);
    }
    void OnMouseDown(rex::ui::MouseEvent &e) override {
      owner->MenuMouse(e, 2);
    }
    void OnMouseUp(rex::ui::MouseEvent &e) override { owner->MenuMouse(e, 3); }
    void OnMouseWheel(rex::ui::MouseEvent &e) override {
      owner->MenuMouse(e, 4);
    }
  } menu_listener{this};
  Impl(rex::Runtime *runtime, rex::ui::Window *w, rex::ui::ImGuiDrawer *d,
       const std::filesystem::path &root)
      : window(w), drawer(d) {
    state->config = root / "pc-input.toml";
    state->Load();
    window->SetCursorVisibility(rex::ui::Window::CursorVisibility::kVisible);
    auto *input =
        static_cast<rex::input::InputSystem *>(runtime->input_system());
    input->AddDriver(std::make_unique<PauseDriver>(state));
    input->SetActiveCallback([s = state] {
      return s->focus.load() && !s->panel.load() && !s->overlay_capture.load();
    });
    dialog = std::make_unique<ControlsDialog>(drawer, state);
    window->AddInputListener(this, 65);
    window->AddInputListener(&menu_listener, 32);
    window->AddListener(this);
  }
  ~Impl() {
    window->RemoveInputListener(this);
    window->RemoveListener(this);
    window->RemoveInputListener(&menu_listener);
    state->pause_until.store(0);
    state->focus.store(false);
    state->panel.store(true);
    XboxNativeMenuEnabled(false);
    dialog.reset();
  }
  void OnKeyDown(rex::ui::KeyEvent &e) override {
    if (e.prev_state())
      return;
    state->SprintKey(e.virtual_key(), true);
    if (e.virtual_key() == VK::kF3) {
      state->ray_tracing = !state->ray_tracing;
      state->Save();
      e.set_handled(true);
      return;
    }
    if (e.virtual_key() == VK::kReturn && state->rebinding < 0 &&
        !state->panel.load() && XboxNativeRequestSkip()) {
      e.set_handled(true);
      return;
    }
    if (e.virtual_key() == VK::kEscape) {
      state->Escape();
      e.set_handled(true);
      return;
    }
    if (e.virtual_key() == VK::kF2) {
      state->TogglePanel();
      e.set_handled(true);
      return;
    }
    if (state->rebinding >= 0) {
      auto key = rex::ui::VirtualKeyToString(e.virtual_key());
      if (key == "Shift" || key == "Control" || key == "Alt")
        return;
      std::string mods;
      if (e.is_shift_pressed())
        mods += "Shift+";
      if (e.is_ctrl_pressed())
        mods += "Ctrl+";
      if (e.is_alt_pressed())
        mods += "Alt+";
      state->Bind(mods + key);
      e.set_handled(true);
    }
  }
  void OnKeyUp(rex::ui::KeyEvent &e) override {
    state->SprintKey(e.virtual_key(), false);
  }
  void OnMouseDown(rex::ui::MouseEvent &e) override {
    if (state->rebinding < 0)
      return;
    const char *key =
        e.button() == rex::ui::MouseEvent::Button::kLeft     ? "LMB"
        : e.button() == rex::ui::MouseEvent::Button::kRight  ? "RMB"
        : e.button() == rex::ui::MouseEvent::Button::kMiddle ? "MMB"
                                                             : "";
    state->Bind(key);
    e.set_handled(true);
  }
  void OnMouseMove(rex::ui::MouseEvent &e) override {
    if (!rex::input::mnk::IsMouseLookActive()) {
      XboxNativeMouseReset();
      window->SetCursorVisibility(rex::ui::Window::CursorVisibility::kVisible);
      return;
    }
    if (state->focus.load() && !state->panel.load())
      XboxNativeMouseMotion(e.dx(), e.dy());
    // The SDK still manages pointer lock and buttons, but must not convert
    // these same deltas into analog-stick input a second time.
    e.set_handled(true);
  }
  void OnLostFocus(rex::ui::UISetupEvent &) override {
    state->focus.store(false);
    state->pause_until.store(0);
    XboxNativeMenuEnabled(false);
    XboxNativeMouseReset();
  }
  void OnGotFocus(rex::ui::UISetupEvent &) override {
    state->focus.store(true);
    XboxNativeMenuEnabled(!state->panel.load());
  }
  void MenuMouse(rex::ui::MouseEvent &e, uint32_t type) {
    if (rex::input::mnk::IsMouseLookActive())
      return;
    if (!state->panel.load() && state->focus.load() &&
        !drawer->GetIO().WantCaptureMouse) {
      uint32_t button = e.button() == rex::ui::MouseEvent::Button::kRight ? 1
                        : e.button() == rex::ui::MouseEvent::Button::kMiddle
                            ? 2
                            : 0;
      XboxNativeMenuMouse(type, float(e.x()), float(e.y()),
                          window->GetActualPhysicalWidth(),
                          window->GetActualPhysicalHeight(), button,
                          float(e.scroll_y()) / 120.f * 3.f);
    }
    // ImGui (layer 64) already received the event. Keep clicks away from the
    // controller's firing/zoom bindings (layer 0); let releases clear old
    // holds.
    if (type != 3)
      e.set_handled(true);
  }
};
NativeControls::NativeControls(rex::Runtime *runtime, rex::ui::Window *window,
                               rex::ui::ImGuiDrawer *drawer,
                               const std::filesystem::path &root)
    : impl_(std::make_unique<Impl>(runtime, window, drawer, root)) {}
NativeControls::~NativeControls() = default;
void NativeControls::ProbeButtons(uint16_t buttons) {
  impl_->state->probe_buttons.store(buttons);
}
void NativeControls::ProbeAntialiasing(int mode) {
  impl_->state->probe_aa.store(mode);
}
void NativeControls::ProbeMove(int16_t x, int16_t y) {
  impl_->state->probe_x.store(x);
  impl_->state->probe_y.store(y);
}
void NativeControls::ProbeKey(uint32_t scancode, bool down) {
  auto *window = impl_->window;
  std::weak_ptr<State> life = impl_->state;
  window->app_context().CallInUIThreadDeferred([window, life, scancode, down] {
    auto state = life.lock();
    if (!state || !state->focus.load())
      return;
    SDL_Event event{};
    event.type = down ? SDL_EVENT_KEY_DOWN : SDL_EVENT_KEY_UP;
    event.key.scancode = SDL_Scancode(scancode);
    event.key.mod = (down && (scancode == SDL_SCANCODE_LSHIFT ||
                              scancode == SDL_SCANCODE_RSHIFT))
                        ? SDL_KMOD_SHIFT
                        : SDL_KMOD_NONE;
    static_cast<rex::ui::WindowSDL *>(window)->HandleKeyEvent(event);
  });
}

#ifdef XBOX_NATIVE_SELF_TEST
void XboxNativeControlsSelfTest(const std::filesystem::path &directory) {
  auto check = [](bool value) {
    if (!value)
      throw std::runtime_error("PC input self-test failed");
  };
  auto state = std::make_shared<State>();
  state->config = directory / "pc-input-test.toml";
  rex::cvar::SetFlagByName("keybind_a", "Space");
  rex::cvar::SetFlagByName("mnk_sensitivity", "1.75");
  state->antialiasing = 2;
  rex::cvar::SetFlagByName("native_sprint", "false");
  rex::cvar::SetFlagByName("native_sprint_multiplier", "1.75");
  rex::cvar::SetFlagByName("native_interpolate_animations", "false");
  state->Save();
  check(state->message == "Reglages enregistres");
  rex::cvar::SetFlagByName("mnk_sensitivity", "0.5");
  state->antialiasing = 0;
  rex::cvar::SetFlagByName("native_sprint", "true");
  rex::cvar::SetFlagByName("native_sprint_multiplier", "1.0");
  rex::cvar::SetFlagByName("native_interpolate_animations", "true");
  state->Load();
  check(rex::cvar::GetFlagByName("mnk_sensitivity") == "1.750000");
  check(state->antialiasing == 2 &&
        rex::cvar::GetFlagByName("native_interpolate_animations") == "false");
  check(rex::cvar::GetFlagByName("native_sprint") == "false" &&
        std::stof(rex::cvar::GetFlagByName("native_sprint_multiplier")) ==
            1.75f);
  state->Save();
  check(state->message == "Reglages enregistres"); // replace an existing file
  {
    std::ofstream old(state->config);
    old << "sensitivity = 2.72\n[bindings]\nkeybind_a = \"Space\"\n";
  }
  state->Load();
  check(rex::cvar::GetFlagByName("mnk_sensitivity") == "1.000000");
  auto old_backup = state->config;
  old_backup += ".analog.bak";
  check(std::filesystem::exists(old_backup));
  state->rebinding = 4;
  state->Bind("Escape");
  check(state->rebinding == 4);
  state->Bind("LMB");
  check(state->BindingValue("keybind_a") == "LMB");
  rex::input::mnk::SetMouseLookActive(true);
  state->TogglePanel();
  check(state->panel.load() && !rex::input::mnk::IsMouseLookActive());
  PauseDriver driver(state);
  rex::input::X_INPUT_STATE value{};
  driver.GetDeviceState({}, &value);
  check(value.gamepad.buttons == X_INPUT_GAMEPAD_START);
  state->pause_until.store(0);
  driver.GetDeviceState({}, &value);
  check(value.gamepad.buttons == 0);
  state->PausePulse();
  state->focus.store(false);
  driver.GetDeviceState({}, &value);
  check(value.gamepad.buttons == 0);
  state->focus.store(true);
  state->TogglePanel();
  check(!state->panel.load() && rex::input::mnk::IsMouseLookActive());
  state->Escape();
  check(!rex::input::mnk::IsMouseLookActive());
  driver.GetDeviceState({}, &value);
  check(value.gamepad.buttons == X_INPUT_GAMEPAD_START);
  state->pause_until.store(0);
  state->Escape();
  check(rex::input::mnk::IsMouseLookActive());
  state->rebinding = 0;
  state->Escape();
  check(state->rebinding == -1);
  // Real SDK keyboard events, including its exact modifier matching.
  rex::cvar::SetFlagByName("mnk_mode", "true");
  rex::cvar::SetFlagByName("keybind_lstick_up", "W");
  rex::cvar::SetFlagByName("keybind_a", "Space");
  rex::cvar::SetFlagByName("keybind_x", "R,E");
  rex::cvar::SetFlagByName("native_sprint", "false");
  state->ApplySprintBindings();
  rex::input::mnk::MnkInputDriver keyboard(nullptr, 0);
  keyboard.Setup();
  std::vector<rex::input::DeviceInfo> devices;
  keyboard.EnumerateDevices(devices);
  check(devices.size() == 1);
  auto key = [&](VK vk, bool down, bool shift = false) {
    rex::ui::KeyEvent event(nullptr, vk, 1, false, shift, false, false, false);
    state->SprintKey(vk, down);
    if (down)
      keyboard.OnKeyDown(event);
    else
      keyboard.OnKeyUp(event);
  };
  auto pad = [&] {
    rex::input::X_INPUT_STATE output{};
    keyboard.GetDeviceState(devices[0].id, &output);
    return output;
  };
  key(VK::kW, true);
  check(pad().gamepad.thumb_ly == 32767);
  key(VK::kShift, true, true);
  check(pad().gamepad.thumb_ly == 0); // reproduce original bug
  rex::cvar::SetFlagByName("native_sprint", "true");
  state->ApplySprintBindings();
  check(pad().gamepad.thumb_ly == 32767);
  key(VK::kSpace, true, true);
  check(uint16_t(pad().gamepad.buttons) & X_INPUT_GAMEPAD_A);
  key(VK::kSpace, false, true);
  key(VK::kShift, false);
  check(pad().gamepad.thumb_ly == 32767);
  state->escape_paused = true; // game was resumed via a mouse click, then F6
  rex::input::mnk::SetMouseLookActive(true);
  key(VK::kLShift, true, true);
  check(XboxNativeSprintIsHeld());
  key(VK::kLShift, false);
  check(!XboxNativeSprintIsHeld());
  key(VK::kW, false);
  check(pad().gamepad.thumb_ly == 0);
  state->Save();
  auto saved_bindings = toml::parse_file(state->config.string());
  check(saved_bindings["bindings"]["keybind_lstick_up"].value_or(
            std::string{}) == "W");
  check(state->BindingValue("keybind_lstick_up") == "W");
  std::fprintf(stderr,
               "check: real SDK W / Shift+W / Shift+Space / left Shift / "
               "mouse-resumed pause / unmodified saved bindings passed\n");
  // Render the actual panel in a CPU-only ImGui context (no SDL/window/GPU).
  std::fprintf(stderr, "check: settings draw context\n");
  auto *previous = ImGui::GetCurrentContext();
  auto *context = ImGui::CreateContext();
  auto &io = ImGui::GetIO();
  io.DisplaySize = ImVec2(1152, 648);
  io.DeltaTime = 1.f / 60.f;
  io.IniFilename = nullptr;
  unsigned char *pixels;
  int width, height;
  io.Fonts->GetTexDataAsRGBA32(&pixels, &width, &height);
  std::fprintf(stderr, "check: font atlas %d x %d\n", width, height);
  io.Fonts->SetTexID((ImTextureID)1);
  state->panel.store(true);
  for (int frame = 0; frame < 2; ++frame) {
    std::fprintf(stderr, "check: settings draw frame %d\n", frame);
    ImGui::NewFrame();
    ControlsDialog::DrawPanel(state, io);
    ImGui::Render();
  }
  check(ImGui::GetDrawData() && ImGui::GetDrawData()->TotalVtxCount > 0);
  ImGui::DestroyContext(context);
  ImGui::SetCurrentContext(previous);
  std::fprintf(stderr, "check: settings draw passed\n");
}
#endif
