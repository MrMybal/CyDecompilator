// Console-only integration check. Loads the user's XEX as data; never launches
// a guest thread or creates a desktop window. Mouse dispatch uses the real
// statically recompiled GFx HandleEvent and queue functions.
#include XBOX_NATIVE_INIT
#include "rex_animation.h"
#include "rex_menu_bridge.h"
#include <bit>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <rex/filesystem.h>
#include <rex/input/mnk/mnk_input_driver.h>
#include <rex/platform/dynlib.h>
#include <rex/runtime.h>
#include <rex/system/xmemory.h>
#include <stdexcept>

void XboxNativeControlsSelfTest(const std::filesystem::path &);
void XboxNativeTimingIntegrationCheck(uint8_t *, uint32_t,
                                      const std::filesystem::path &);
extern "C" REX_FUNC(sub_82ACEE48);
int main(int argc, char **argv) {
  try {
    if (argc != 3)
      throw std::runtime_error(
          "Expected game directory and fresh test directory");
    auto directory = std::filesystem::absolute(argv[2]);
    std::filesystem::create_directories(directory);
    auto check = [](bool value, const char *name) {
      if (!value)
        throw std::runtime_error(name);
    };
    // Match ReXApp: load native plugins before reserving the guest arena.
    rex::platform::DynamicLibrary plugin;
    std::cerr << "check: loading FPS plugin\n";
    check(plugin.Load(std::filesystem::absolute(argv[0]).parent_path() /
                      "rexgpu-xenos-occlusion.dll"),
          "FPS plugin unavailable");
    std::cerr << "check: FPS plugin loaded\n";
    auto frames = plugin.GetSymbol<uint64_t (*)()>("rex_gpu_guest_frame_count");
    check(frames && frames() == 0, "Guest frame counter export unavailable");
    rex::Runtime runtime(std::filesystem::absolute(argv[1]), directory / "user",
                         directory / "cache", directory / "metadata");
    rex::RuntimeConfig config;
    config.tool_mode = true;
    if (runtime.Setup(PPCImageConfig, std::move(config)) != 0 ||
        runtime.LoadXexImage("game:\\default.xex") != 0)
      throw std::runtime_error("Cannot initialize CPU test runtime");
    std::cerr << "check: CPU runtime ready\n";
    auto *base = runtime.virtual_membase();
    PPCContext ctx{};
    ctx.r1.u32 = runtime.memory()->SystemHeapAlloc(0x20000) + 0x1F000;
    auto create_movie = [&] {
      auto root = runtime.memory()->SystemHeapAlloc(0x3000);
      std::memset(base + root, 0, 0x3000);
      REX_STORE_U32(root, 0x82006680);
      REX_STORE_U32(root + 0x40, 1152);
      REX_STORE_U32(root + 0x44, 648);
      REX_STORE_U32(root + 0x78, 0x3F800000);
      REX_STORE_U32(root + 0x7C, 0x3F800000);
      REX_STORE_U32(root + 0x2478, 1u << 18); // GFx visible flag
      ctx.r3.u64 = root;
      XboxNativeGfxAdvance(ctx, base);
      return root;
    };
    rex::input::mnk::SetMouseLookActive(false);
    uint32_t root = create_movie(), second = create_movie();
    ctx.r3.u64 = root;
    ctx.f1.f64 = 42.5;
    ctx.lr = 0x12345678;
    PPCContext before = ctx;
    XboxNativeMenuMouse(1, 800, 600, 1600, 1200);
    XboxNativeGfxAdvance(ctx, base);
    check(std::memcmp(&ctx, &before, sizeof(ctx)) == 0,
          "Guest registers changed by mouse bridge");
    check(REX_LOAD_U32(root + 0x9C4) == 1, "Mouse cursor not enabled");
    check(REX_LOAD_U32(root + 0x92C) & 1,
          "Move not received by real GFx queue");
    union {
      float f;
      uint32_t u;
    } x, y;
    x.u = REX_LOAD_U32(root + 0x90C);
    y.u = REX_LOAD_U32(root + 0x910);
    check(x.f == 11520.f && y.f == 6480.f,
          "Letterbox coordinate conversion incorrect");
    ctx.r3.u64 = second;
    XboxNativeGfxAdvance(ctx, base);
    check(REX_LOAD_U32(second + 0x92C) & 1,
          "Mouse event not broadcast to second movie");
    ctx.r3.u64 = root;
    XboxNativeMenuMouse(2, 576, 324, 1152, 648);
    XboxNativeMenuMouse(3, 576, 324, 1152, 648);
    XboxNativeMenuMouse(4, 576, 324, 1152, 648, 0, 3.f);
    XboxNativeGfxAdvance(ctx, base);
    check(REX_LOAD_U32(root + 0x908) == 3,
          "Click/release/wheel not received by real GFx queue");
    check(REX_LOAD_U8(root + 0x143) == 0, "Wrong GFx mouse-down flag");
    check(REX_LOAD_U8(root + 0x157) == 0x80, "Wrong GFx mouse-up flag");
    check(REX_LOAD_U8(root + 0x16B) == 0x20, "Wrong GFx wheel flag");
    rex::input::mnk::SetMouseLookActive(true);
    XboxNativeMenuMouse(2, 1, 1, 1152, 648);
    XboxNativeGfxAdvance(ctx, base);
    check(REX_LOAD_U32(root + 0x908) == 3, "Gameplay click leaked into menu");
    // Independent semantic oracle: the game's own NotifyMouseState queues
    // flag 0 for a new pressed button, 0x80 for its release. Merely testing our
    // chosen event numbers against copied constants hid the old inversion.
    XboxNativeMenuEnabled(false);
    ctx.r3.u32 = root;
    ctx.r6.u32 = 1;
    ctx.r7.u32 = 0;
    ctx.f1.f64 = 576;
    ctx.f2.f64 = 324;
    sub_82ACEE48(ctx, base);
    check(REX_LOAD_U8(root + 0x17F) == 0,
          "NotifyMouseState disagrees with physical down");
    REX_STORE_U32(root + 0x940,
                  1); // mouse state after the queued down is processed
    ctx.r3.u32 = root;
    ctx.r6.u32 = 0;
    ctx.r7.u32 = 0;
    sub_82ACEE48(ctx, base);
    check(REX_LOAD_U8(root + 0x193) == 0x80,
          "NotifyMouseState disagrees with physical up");
    XboxNativeMenuEnabled(true);
    rex::input::mnk::SetMouseLookActive(false);
    auto queued = REX_LOAD_U32(root + 0x908);
    ctx.r3.u32 = root;
    ctx.r6.u32 = 0;
    ctx.r7.u32 = 0;
    sub_82ACEE48(ctx, base);
    check(REX_LOAD_U32(root + 0x908) == queued,
          "Kinect reset cancelled the physical PC cursor");
    ctx.r3.u32 = root;
    ctx.r7.u32 = 1;
    check(XboxNativeMenuOwnsMouse(ctx, base),
          "Second virtual Kinect cursor can steal PC menu focus");
    ctx.r7.u32 = 2;
    check(!XboxNativeMenuOwnsMouse(ctx, base),
          "Unrelated cursor was taken over");
    // Relative movement is linear, preserves fractional pixels, drains once
    // per player update and never changes the other player's input.
    rex::cvar::SetFlagByName("mnk_mode", "true");
    rex::cvar::SetFlagByName("mnk_sensitivity", "1.0");
    rex::input::mnk::SetMouseLookActive(true);
    XboxNativeMouseReset();
    ctx.r27.u32 = root + 0x2800;
    ctx.r28.s32 = 0;
    REX_STORE_U32(ctx.r27.u32 + 12, 0);
    REX_STORE_U32(ctx.r27.u32 + 16, 0);
    XboxNativeMouseMotion(.25f, -.5f);
    XboxNativeMouseMotion(.25f, -.5f);
    XboxNativePlayerLook(ctx, base);
    x.u = REX_LOAD_U32(ctx.r27.u32 + 12);
    y.u = REX_LOAD_U32(ctx.r27.u32 + 16);
    check(std::abs(x.f + .001f) < 1e-7f && std::abs(y.f - .002f) < 1e-7f,
          "Fractional direct aim was lost or accelerated");
    XboxNativePlayerLook(ctx, base);
    check(REX_LOAD_U32(ctx.r27.u32 + 12) == x.u,
          "Mouse delta was replayed on another input poll");
    XboxNativeMouseMotion(10, 10);
    XboxNativeMouseReset();
    XboxNativePlayerLook(ctx, base);
    check(REX_LOAD_U32(ctx.r27.u32 + 12) == x.u,
          "Focus/capture reset retained old motion");
    PPCContext pacing{};
    pacing.f0.f64 = 1.0 / 29.97;
    pacing.f13.f64 = .017;
    pacing.r3.u32 = 0x12345678;
    rex::cvar::SetFlagByName("native_unlock_fps", "false");
    XboxNativeFramePacing(pacing);
    check(pacing.f0.f64 > .033, "Original FPS mode changed");
    rex::cvar::SetFlagByName("native_unlock_fps", "true");
    XboxNativeFramePacing(pacing);
    check(pacing.f0.f64 == 0 && pacing.f13.f64 == .017 &&
              pacing.r3.u32 == 0x12345678,
          "FPS unlock changed elapsed time or guest registers");
    // Sprint changes the selected biped's desired horizontal speed, not tags,
    // simulation time, player records, other players or vehicle movement.
    auto unit = runtime.memory()->SystemHeapAlloc(0x1000);
    auto player = unit + 0x800;
    std::memset(base + unit, 0, 0x1000);
    REX_STORE_U32(unit + 0x11C, 0xFFFFFFFFu);
    REX_STORE_U32(unit + 0x278, std::bit_cast<uint32_t>(1.f));
    ctx.r8.u32 = player;
    ctx.r31.u32 = unit;
    rex::cvar::SetFlagByName("native_sprint", "true");
    rex::cvar::SetFlagByName("native_sprint_multiplier", "1.5");
    XboxNativeSprintHeld(true);
    ctx.f31.f64 = .8;
    XboxNativeSprintSpeed(ctx, base);
    check(std::abs(ctx.f31.f64 - 1.2) < 1e-6,
          "Shift did not multiply the existing speed modifier");
    XboxNativeSprintHeld(false);
    ctx.f31.f64 = .8;
    XboxNativeSprintSpeed(ctx, base);
    check(ctx.f31.f64 == .8, "Released Shift retained sprint");
    XboxNativeSprintHeld(true);
    REX_STORE_U16(player + 2, 1);
    XboxNativeSprintSpeed(ctx, base);
    check(ctx.f31.f64 == .8, "Sprint affected another player");
    REX_STORE_U16(player + 2, 0);
    REX_STORE_U32(unit + 0x11C, 0x12340001);
    XboxNativeSprintSpeed(ctx, base);
    check(ctx.f31.f64 == .8, "Sprint affected an occupied vehicle");
    REX_STORE_U32(unit + 0x11C, 0xFFFFFFFFu);
    REX_STORE_U32(unit + 0x278, std::bit_cast<uint32_t>(-1.f));
    XboxNativeSprintSpeed(ctx, base);
    check(ctx.f31.f64 == .8, "Backwards movement received forward sprint");
    REX_STORE_U32(unit + 0x278, std::bit_cast<uint32_t>(1.f));
    REX_STORE_U32(unit + 0x50C, std::bit_cast<uint32_t>(1.f));
    XboxNativeSprintSpeed(ctx, base);
    check(ctx.f31.f64 == .8, "Crouching received sprint");
    REX_STORE_U32(unit + 0x50C, 0);
    XboxNativeMouseReset();
    XboxNativeSprintSpeed(ctx, base);
    check(ctx.f31.f64 == .8, "Pause/focus reset retained sprint");
    std::cerr << "check: sprint speed / existing modifier / release / local "
                 "player / vehicle / crouch / reset passed\n";
    XboxNativeControlsSelfTest(directory);
    XboxNativeAnimationIntegrationCheck(
        base, runtime.memory()->SystemHeapAlloc(0x40000));
    XboxNativeTimingIntegrationCheck(
        base, runtime.memory()->SystemHeapAlloc(0x40000), directory);
    std::cout << "PASS: real GFx input / NotifyMouseState press-release oracle "
                 "/ Kinect isolation / direct fractional aim / delta draining "
                 "/ FPS pacing / saved bindings / Escape / settings rendering "
                 "/ guest FPS export\n";
    return 0;
  } catch (const std::exception &e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
