#include "rex_menu_bridge.h"
#include XBOX_NATIVE_PCH
#include <algorithm>
#include <atomic>
#include <bit>
#include <chrono>
#include <cmath>
#include <deque>
#include <mutex>
#include <rex/cvar.h>
#include <rex/input/mnk/mnk_input_driver.h>
#include <rex/logging.h>
#include <set>
#include <unordered_map>
#include <vector>

REXCVAR_DEFINE_BOOL(native_sprint, true, "PC", "Hold Shift to sprint on foot");
REXCVAR_DEFINE_DOUBLE(native_sprint_multiplier, 1.5, "PC",
                      "Forward sprint speed multiplier");
REXCVAR_DEFINE_STRING(native_start_map, "", "PC",
                      "Direct campaign map: a10,a30,a50,b30,b40,c10,c20,c40,d20,d40");

extern "C" REX_FUNC(sub_82ACE988);
extern "C" REX_FUNC(sub_822FB330);
extern "C" REX_FUNC(sub_826369A8);
extern "C" REX_FUNC(sub_823DCF70);
namespace {
struct Mouse {
  uint64_t sequence;
  uint32_t type, button, width, height;
  float x, y, wheel;
};
struct Movie {
  uint64_t sequence = 0;
  uint32_t held = 0;
  Mouse position{};
};
std::mutex bridge_mutex;
std::deque<Mouse> events;
std::unordered_map<uint32_t, Movie> movies;
uint64_t sequence = 0;
bool enabled = true;
bool pointer_available = false;
thread_local unsigned native_dispatch_depth = 0;
std::mutex look_mutex;
struct Motion {
  std::chrono::steady_clock::time_point time;
  double x, y;
};
std::deque<Motion> look_motion;
std::atomic<bool> sprint_held{false};
std::atomic<bool> cinematic_skippable{false};
std::atomic<int64_t> skip_until{0};
std::atomic<int64_t> sprint_until{0};
std::atomic<int64_t> map_ui_ready{0};
std::mutex map_mutex;
std::string pending_map;
bool boot_map_checked = false;
int64_t NowMs() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::steady_clock::now().time_since_epoch())
      .count();
}

void Dispatch(PPCContext &ctx, uint8_t *base, uint32_t root,
              const Mouse &event) {
  uint32_t width = REX_LOAD_U32(root + 0x40),
           height = REX_LOAD_U32(root + 0x44);
  if (!width || !height || width > 16384 || height > 16384 || !event.width ||
      !event.height)
    return;
  float scale =
      std::min(float(event.width) / width, float(event.height) / height);
  float x = (event.x - (event.width - width * scale) * .5f) / scale;
  float y = (event.y - (event.height - height * scale) * .5f) / scale;
  if (rex::cvar::GetFlagByName("present_letterbox") == "false") {
    x = event.x * float(width) / event.width;
    y = event.y * float(height) / event.height;
  }
  // Call on the guest UI thread, before its normal Advance. The input event
  // lives in a caller-owned stack frame; every guest register is restored.
  PPCContext saved = ctx;
  struct Restore {
    PPCContext &live;
    PPCContext saved;
    ~Restore() { live = saved; }
  } restore{ctx, saved};
  uint32_t stack = (ctx.r1.u32 - 512) & ~15u;
  uint32_t message = stack + 128;
  REX_STORE_U32(stack, ctx.r1.u32);
  for (uint32_t i = 0; i < 24; i += 4)
    REX_STORE_U32(message + i, 0);
  REX_STORE_U32(message, event.type);
  union {
    float f;
    uint32_t u;
  } value;
  value.f = x;
  REX_STORE_U32(message + 4, value.u);
  value.f = y;
  REX_STORE_U32(message + 8, value.u);
  value.f = event.wheel;
  REX_STORE_U32(message + 12, value.u);
  REX_STORE_U32(message + 16, event.button);
  REX_STORE_U32(message + 20, 0); // mouse/controller index 0
  ctx.r1.u32 = stack;
  ctx.r3.u64 = root;
  ctx.r4.u64 = message;
  struct DispatchScope {
    DispatchScope() { ++native_dispatch_depth; }
    ~DispatchScope() { --native_dispatch_depth; }
  } scope;
  sub_82ACE988(ctx, base);
}
} // namespace

void XboxNativeSprintHeld(bool held) {
  sprint_held.store(held);
  if (!held)
    sprint_until.store(0);
}
bool XboxNativeSprintIsHeld() { return sprint_held.load(); }
bool XboxNativeRequestSkip() {
  if (!cinematic_skippable.load())
    return false;
  skip_until.store(NowMs() + 500);
  return true;
}
bool XboxNativeQueueMap(std::string_view map) {
  constexpr std::string_view maps[] = {"a10", "a30", "a50", "b30", "b40",
                                       "c10", "c20", "c40", "d20", "d40"};
  if (std::find(std::begin(maps), std::end(maps), map) == std::end(maps))
    return false;
  std::lock_guard lock(map_mutex);
  pending_map = map;
  return true;
}
// Let the normal campaign frontend prepare its session before LoadLevelSolo.
// Starting Blam alone leaves the menu active; calling Saber during an arbitrary
// game update can skip frontend loading state. Boot pulses use the same native
// input path as the normal Accept button and stop as soon as the launch arrives.
uint16_t XboxNativeBootButtons() {
  std::lock_guard lock(map_mutex);
  auto ready = map_ui_ready.load();
  if (pending_map.empty() || !ready)
    return 0;
  auto elapsed = NowMs() - ready;
  return elapsed >= 1500 && elapsed < 10500 && elapsed % 1500 < 250
             ? 0x1000 : 0;
}
namespace {
void ReplaceCampaignArgument(PPCContext &ctx, uint8_t *base, const std::string &map) {
  struct Restore {
    PPCContext &live;
    PPCContext saved;
    ~Restore() { live = saved; }
  } restore{ctx, ctx};
  auto original_holder = ctx.r4.u32;
  auto stack = (ctx.r1.u32 - 1024) & ~15u;
  auto holder = stack + 96;
  auto argument = stack + 256;
  REX_STORE_U32(stack, ctx.r1.u32);
  REX_STORE_U32(holder, 0);
  for (size_t i = 0; i <= map.size(); ++i)
    REX_STORE_U8(argument + uint32_t(i), map.c_str()[i]);
  ctx.r1.u32 = stack;
  ctx.r3.u64 = holder;
  ctx.r4.u64 = argument;
  ctx.r5.s64 = -1;
  ctx.r6.u64 = 0;
  sub_822FB330(ctx, base);
  // The game's own shared-string assignment retains the replacement and
  // releases the previous argument. The normal launch consumes its reference.
  ctx.r3.u64 = original_holder;
  ctx.r4.u64 = holder;
  sub_826369A8(ctx, base);
  ctx.r3.u64 = holder;
  sub_823DCF70(ctx, base);
  REXLOG_INFO("[native-map] Campaign argument selected {}", map);
}
} // namespace
void XboxNativeObserveCampaignLaunch(PPCContext &ctx, uint8_t *base) {
  std::string map;
  {
    std::lock_guard lock(map_mutex);
    map.swap(pending_map);
  }
  if (!map.empty() && REX_LOAD_U32(ctx.r3.u32) == 0x820086BC)
    ReplaceCampaignArgument(ctx, base, map);
}
void XboxNativeSaberMapArgument(PPCContext &ctx, uint8_t *base) {
  static bool applied = false;
  auto wanted = rex::cvar::GetFlagByName("native_start_map");
  if (applied || wanted.empty() || !ctx.r4.u32)
    return;
  constexpr std::string_view maps[] = {"a10", "a30", "a50", "b30", "b40",
                                       "c10", "c20", "c40", "d20", "d40"};
  if (std::find(std::begin(maps), std::end(maps), wanted) == std::end(maps))
    return;
  auto header = REX_LOAD_U32(ctx.r4.u32);
  if (!header)
    return;
  std::string original;
  for (uint32_t i = 0; i < 260; ++i) {
    auto c = REX_LOAD_U8(header + 12 + i);
    if (!c) break;
    if (c < 32 || c > 126) return;
    original += char(c);
  }
  auto slash = original.find_last_of("\\/");
  auto stem = original.substr(slash == std::string::npos ? 0 : slash + 1);
  if (stem.size() != 3 && (stem.size() != 6 || !stem.ends_with(".lg")))
    return;
  auto old = stem.substr(0, 3);
  if (std::find(std::begin(maps), std::end(maps), old) == std::end(maps))
    return; // Never replace ui.lg, a menu or another engine resource.
  auto replacement = original;
  for (size_t offset = 0; (offset = replacement.find(old, offset)) != std::string::npos; offset += wanted.size())
    replacement.replace(offset, old.size(), wanted);
  applied = true;
  ReplaceCampaignArgument(ctx, base, replacement);
  REXLOG_INFO("[native-map] Saber scene {} -> {}", original, replacement);

}
void XboxNativeDirectMapTick(PPCContext &, uint8_t *) {
  if (!boot_map_checked && map_ui_ready.load()) {
    boot_map_checked = true;
    auto map = rex::cvar::GetFlagByName("native_start_map");
    if (!map.empty() && !XboxNativeQueueMap(map))
      REXLOG_WARN("[native-map] Unsupported direct map {}", map);
  }
}
void XboxNativeSkipTick(PPCContext &, uint8_t *base) {
  uint32_t cinematic = REX_LOAD_U32(0x83770310);
  bool can_skip =
      cinematic && REX_LOAD_U8(cinematic + 9) && REX_LOAD_U8(cinematic + 0xA);
  cinematic_skippable.store(can_skip);
  int64_t requested = skip_until.exchange(0);
  if (can_skip && requested > NowMs())
    // 822CD968 checks this request then uses the normal script skip path.
    REX_STORE_U8(0x8376FD13, 1);
}
bool XboxNativeSprintActive() {
  return sprint_held.load() && NowMs() < sprint_until.load() &&
         rex::input::mnk::IsMouseLookActive() &&
         rex::cvar::GetFlagByName("native_sprint") == "true";
}
void XboxNativeSprintSpeed(PPCContext &ctx, uint8_t *base) {
  // These sites run only after the biped has loaded its owning player's speed.
  // Apply to desired horizontal velocity, preserving the game's existing stun
  // and crouch modifiers. No tag, timer, weapon or global speed is overwritten.
  uint32_t player = ctx.r8.u32, unit = ctx.r31.u32;
  if (!player || !unit || REX_LOAD_U16(player + 2) != 0 ||
      REX_LOAD_U16(unit + 0xB4) != 0 ||
      REX_LOAD_U32(unit + 0x11C) != 0xFFFFFFFFu)
    return;
  if (REX_LOAD_U32(unit + 0x4CC) & 1u) {
    sprint_until.store(0);
    return;
  }
  float forward = std::bit_cast<float>(REX_LOAD_U32(unit + 0x278));
  float crouch = std::bit_cast<float>(REX_LOAD_U32(unit + 0x50C));
  static auto last_probe = std::chrono::steady_clock::time_point{};
  auto now = std::chrono::steady_clock::now();
  if (now - last_probe > std::chrono::milliseconds(250) &&
      rex::cvar::GetFlagByName("native_input_probe") == "true") {
    REXLOG_INFO("[native-movement] unit={:08X} shift={} forward={} crouch={} "
                "base_speed={} position={},{},{}",
                unit, sprint_held.load(), forward, crouch, ctx.f31.f64,
                std::bit_cast<float>(REX_LOAD_U32(unit + 0x5C)),
                std::bit_cast<float>(REX_LOAD_U32(unit + 0x60)),
                std::bit_cast<float>(REX_LOAD_U32(unit + 0x64)));
    last_probe = now;
  }
  if (!sprint_held.load() || !rex::input::mnk::IsMouseLookActive() ||
      rex::cvar::GetFlagByName("native_sprint") != "true")
    return;
  if (!std::isfinite(forward) || forward <= .1f || !std::isfinite(crouch) ||
      crouch > .1f)
    return;
  // Host-side configurable arithmetic must not inherit guest exception masks
  // or leave its rounding/sticky flags in the guest floating-point policy.
  using Platform = PPCFPSCRRegister::Platform;
  struct FloatPolicy {
    uint32_t saved = Platform::getcsr();
    FloatPolicy() {
      auto control = saved & ~uint32_t(Platform::RoundMaskVal);
      Platform::InitHostExceptions(control);
      Platform::setcsr(control);
    }
    ~FloatPolicy() { Platform::setcsr(saved); }
  } floating_point_policy;
  double factor =
      std::stod(rex::cvar::GetFlagByName("native_sprint_multiplier"));
  if (std::isfinite(factor)) {
    ctx.f31.f64 *= std::clamp(factor, 1., 2.);
    if (factor > 1.)
      sprint_until.store(NowMs() + 100);
  }
}

void XboxNativeMouseReset() {
  XboxNativeSprintHeld(false);
  std::lock_guard lock(look_mutex);
  look_motion.clear();
}
void XboxNativeVideoPolicy(uint32_t object, uint8_t *base) {
  if (rex::cvar::GetFlagByName("native_unlock_fps") != "true")
    return;
  REX_STORE_U32(object + 0x30, 0); // Video.VIDEO_Wait_VSync
  REX_STORE_U32(object + 0x34, 0); // Video.VIDEO_Force_VSync (2 on Xbox)
  REXLOG_INFO("[native-video] Removed half-rate VSync at {:08X}", object);
}
void XboxNativeSleepProbe(PPCContext &ctx, uint8_t *) {
  if (rex::cvar::GetFlagByName("native_input_probe") != "true")
    return;
  static std::mutex lock;
  static std::set<std::pair<uint32_t, uint32_t>> sites;
  std::lock_guard guard(lock);
  if (sites.emplace(uint32_t(ctx.lr), ctx.r3.u32).second)
    REXLOG_INFO("[native-probe] Sleep caller {:08X}, milliseconds {}",
                uint32_t(ctx.lr), ctx.r3.s32);
}
void XboxNativeFramePacing(PPCContext &ctx) {
  // Only the two presentation-wait thresholds in 823D7150. Its elapsed-time
  // measurement and all simulation/cinematic clocks stay in original code.
  if (rex::cvar::GetFlagByName("native_unlock_fps") == "true")
    ctx.f0.f64 = 0;
}
void XboxNativeGfxProcessMouse(PPCContext &ctx, uint8_t *base) {
  if (rex::cvar::GetFlagByName("native_input_probe") != "true")
    return;
  uint32_t e = ctx.r5.u32;
  if (REX_LOAD_U16(e + 12))
    REXLOG_INFO("[native-mouse] Button root {:08X} mask {:04X} flags {:02X}, "
                "mouse {}, previous {:08X}",
                ctx.r3.u32, REX_LOAD_U16(e + 12), REX_LOAD_U8(e + 15),
                REX_LOAD_U8(e + 16), REX_LOAD_U32(ctx.r3.u32 + 0x940));
}
void XboxNativeMouseMotion(float dx, float dy) {
  if (!std::isfinite(dx) || !std::isfinite(dy))
    return;
  std::lock_guard lock(look_mutex);
  auto now = std::chrono::steady_clock::now();
  while (!look_motion.empty() &&
         (now - look_motion.front().time > std::chrono::milliseconds(150) ||
          look_motion.size() >= 4096))
    look_motion.pop_front();
  look_motion.push_back({now, dx, dy});
}
void XboxNativePlayerLook(PPCContext &ctx, uint8_t *base) {
  // Verified sites 82C6E9A4 / 82C6EAA0: local player in r28, output in r27.
  // Both sites are inside the game's "input enabled" branch. Cutscenes and
  // paused control updates don't reach them. Only local player zero owns MnK.
  if (ctx.r28.s32 != 0)
    return;
  double dx = 0, dy = 0;
  {
    std::lock_guard lock(look_mutex);
    auto now = std::chrono::steady_clock::now();
    for (auto &event : look_motion)
      if (now - event.time <= std::chrono::milliseconds(150)) {
        dx += event.x;
        dy += event.y;
      }
    look_motion.clear();
  }
  if (!rex::input::mnk::IsMouseLookActive() ||
      rex::cvar::GetFlagByName("mnk_mode") != "true")
    return;
  const double radians =
      .002 * std::stod(rex::cvar::GetFlagByName("mnk_sensitivity"));
  union {
    float f;
    uint32_t u;
  } yaw, pitch;
  yaw.u = REX_LOAD_U32(ctx.r27.u32 + 12);
  pitch.u = REX_LOAD_U32(ctx.r27.u32 + 16);
  if (!std::isfinite(yaw.f) || !std::isfinite(pitch.f))
    return;
  if ((dx || dy) && rex::cvar::GetFlagByName("native_input_probe") == "true")
    REXLOG_INFO("[native-look] player {} pixels {},{} -> radians {},{}",
                ctx.r28.s32, dx, dy, -dx * radians, -dy * radians);
  yaw.f -= float(dx * radians);
  pitch.f -= float(dy * radians);
  REX_STORE_U32(ctx.r27.u32 + 12, yaw.u);
  REX_STORE_U32(ctx.r27.u32 + 16, pitch.u);
}

void XboxNativeMenuEnabled(bool value) {
  std::lock_guard lock(bridge_mutex);
  enabled = value;
}
void XboxNativeMenuMouse(uint32_t type, float x, float y, uint32_t width,
                         uint32_t height, uint32_t button, float wheel) {
  if (type < 1 || type > 4 || button > 2 || !width || !height ||
      !std::isfinite(x) || !std::isfinite(y))
    return;
  std::lock_guard lock(bridge_mutex);
  pointer_available = true;
  Mouse event{++sequence, type, button, width, height, x, y, wheel};
  if (type == 1 && !events.empty() && events.back().type == 1)
    events.back() = event;
  else
    events.push_back(event);
  while (events.size() > 256)
    events.pop_front();
}
bool XboxNativeMenuOwnsMouse(PPCContext &ctx, uint8_t *base) {
  // Halo updates two virtual Kinect cursors through NotifyMouseState every
  // frame. Their off-screen position / released buttons otherwise cancel a
  // physical mouse press between its down and up events. Reserve cursor zero
  // while the PC cursor is free. Both virtual cursors resume in captured mode.
  if (ctx.r7.u32 >= 2 || REX_LOAD_U32(ctx.r3.u32) != 0x82006680)
    return false;
  std::lock_guard lock(bridge_mutex);
  return enabled && pointer_available && !rex::input::mnk::IsMouseLookActive();
}
bool XboxNativeIgnoreGuestMouse(PPCContext &ctx, uint8_t *base) {
  if (native_dispatch_depth || REX_LOAD_U32(ctx.r3.u32) != 0x82006680)
    return false;
  uint32_t type = REX_LOAD_U32(ctx.r4.u32);
  if (type < 1 || type > 4)
    return false;
  std::lock_guard lock(bridge_mutex);
  return enabled && pointer_available && !rex::input::mnk::IsMouseLookActive();
}
void XboxNativeGfxAdvance(PPCContext &ctx, uint8_t *base) {
  const uint32_t root = ctx.r3.u32;
  // Exact Halo GFxMovieRoot vtable; never apply this layout to another object.
  if (REX_LOAD_U32(root) != 0x82006680)
    return;
  int64_t unseen = 0;
  map_ui_ready.compare_exchange_strong(unseen, NowMs());
  std::vector<Mouse> batch;
  {
    std::lock_guard lock(bridge_mutex);
    auto [it, fresh] = movies.try_emplace(root);
    auto &movie = it->second;
    if (fresh) {
      movie.sequence = sequence;
      REXLOG_INFO("[native-ui] GFx root {:08X}, viewport {}x{}, rectangle "
                  "{},{} {}x{}, cursors {}, flags {:08X}",
                  root, REX_LOAD_U32(root + 0x40), REX_LOAD_U32(root + 0x44),
                  REX_LOAD_U32(root + 0x48), REX_LOAD_U32(root + 0x4C),
                  REX_LOAD_U32(root + 0x50), REX_LOAD_U32(root + 0x54),
                  REX_LOAD_U32(root + 0x9C4), REX_LOAD_U32(root + 0x2478));
    }
    bool accept = enabled && !rex::input::mnk::IsMouseLookActive();
    if (!accept) {
      for (uint32_t button = 0; button < 3; ++button)
        if (movie.held & (1u << button)) {
          auto up = movie.position;
          up.type = 3;
          up.button = button;
          batch.push_back(up);
        }
      movie.held = 0;
      movie.sequence = sequence;
    } else {
      for (auto event : events)
        if (event.sequence > movie.sequence) {
          batch.push_back(event);
          movie.position = event;
          if (event.type == 2)
            movie.held |= 1u << event.button;
          if (event.type == 3)
            movie.held &= ~(1u << event.button);
        }
      movie.sequence = sequence;
    }
  }
  if (batch.empty())
    return;
  // Xbox builds may start with zero mouse cursors. HandleEvent rejects index
  // zero in that state. Enabling one cursor uses the verified cursor-count
  // field.
  uint32_t cursors = REX_LOAD_U32(root + 0x9C4);
  if (cursors == 0)
    REX_STORE_U32(root + 0x9C4, 1);
  if (cursors > 4)
    return;
  for (const auto &event : batch)
    Dispatch(ctx, base, root, event);
}
