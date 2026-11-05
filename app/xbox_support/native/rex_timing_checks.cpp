// Console-only timing experiments on the exact, statically compiled game.
// Never linked into the playable executable and never edits the source XEX.
#include XBOX_NATIVE_PCH
#include "rex_physics.h"
#include <array>
#include <bit>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <rex/cvar.h>
#include <stdexcept>
#include <vector>

extern "C" REX_FUNC(sub_822D1D80);
extern "C" REX_FUNC(sub_82D36470);
extern "C" REX_FUNC(sub_82D36520);

void XboxNativeTimingIntegrationCheck(uint8_t *base, uint32_t arena,
                                      const std::filesystem::path &directory) {
  auto check = [](bool ok, const char *reason) {
    if (!ok)
      throw std::runtime_error(reason);
  };
  auto original_hz = rex::cvar::GetFlagByName("native_biped_physics_hz");
  rex::cvar::SetFlagByName("native_biped_physics_hz", "30");
  // The scheduler's local/offline branch. Preserve every global it touches.
  struct SavedMemory {
    uint8_t *base;
    struct Item {
      uint32_t address;
      std::vector<uint8_t> data;
    };
    std::vector<Item> items;
    void save(uint32_t address, size_t size) {
      items.push_back({address, {base + address, base + address + size}});
    }
    ~SavedMemory() {
      for (auto &item : items)
        std::memcpy(base + item.address, item.data.data(), item.data.size());
    }
  } saved{base};
  for (uint32_t address : {0x8376FAECu, 0x8376FAF0u, 0x8376FAF4u, 0x8376FAF8u,
                           0x8376FB00u, 0x834674ACu, 0x83437468u, 0x83467518u})
    saved.save(address, 4);
  saved.save(0x8376FCF8, 2); // connection type: local
  saved.save(0x83553CB1, 2); // single-step/debug flags
  saved.save(0x834B38C8, 4); // player table, empty during physics tests
  saved.save(0x8347A260, 4); // gravity, in displacement per tick squared
  saved.save(0x837E78E0, 4); // collision move recursion counter
  std::memset(base + arena, 0, 0x40000);
  REX_STORE_U32(0x8376FAEC, arena);
  REX_STORE_U32(0x8376FAF0, 0);
  REX_STORE_U32(0x8376FAF4, 0);
  REX_STORE_U32(0x8376FAF8, 0);
  REX_STORE_U32(0x834674AC, 0xFFFFFFFFu);
  REX_STORE_U32(0x83437468, 0xFFFFFFFFu);
  REX_STORE_U16(0x8376FCF8, 0);
  REX_STORE_U8(0x83553CB1, 0);
  REX_STORE_U8(0x83553CB2, 0);
  auto put = [&](uint32_t p, float value) {
    REX_STORE_U32(p, std::bit_cast<uint32_t>(value));
  };
  auto schedule = [&](float speed, int render_hz) {
    put(arena + 0x18, speed);
    put(arena + 0x1C, 0);
    int total = 0;
    for (int i = 0; i < render_hz * 2; ++i) {
      PPCContext ctx{};
      ctx.fpscr.InitHost();
      ctx.r1.u32 = arena + 0x3F000;
      ctx.f1.f64 = float(1.f / render_hz);
      ctx.r4.u32 = 0;
      sub_822D1D80(ctx, base);
      total += ctx.r3.s32;
      float remainder = std::bit_cast<float>(REX_LOAD_U32(arena + 0x1C));
      check(std::isfinite(remainder) && remainder >= 0 && remainder < .034f,
            "Timing scheduler produced an invalid remainder");
    }
    return total;
  };
  std::array<int, 4> render_rates{30, 60, 120, 240}, baseline{};
  for (size_t i = 0; i < render_rates.size(); ++i) {
    baseline[i] = schedule(1, render_rates[i]);
    check(std::abs(baseline[i] - 60) <= 1,
          "Original simulation cadence changed with presentation FPS");
  }
  int twice = schedule(2, 120);
  check(std::abs(twice - 120) <= 1,
        "Scheduler acceleration experiment did not reach twice the tick rate");

  // A real biped timing kernel converts seconds to an 8-bit tick countdown.
  // Its output does not adapt when the scheduler runs twice as often.
  auto stun_ticks = [&] {
    auto unit = arena + 0x1000, definition = arena + 0x2000;
    put(definition + 0x3D4, 1);
    put(definition + 0x3D8, 2);
    put(definition + 0x3DC, 0);
    put(definition + 0x3E0, 7.5f);
    put(definition + 0x3E4, 15);
    PPCContext ctx{};
    ctx.fpscr.InitHost();
    ctx.r1.u32 = arena + 0x3F000;
    ctx.r3.u32 = unit;
    ctx.r4.u32 = definition;
    ctx.f1.f64 = .125;
    sub_82D36470(ctx, base);
    return REX_LOAD_U8(unit + 0x4D1);
  };
  put(arena + 0x18, 1);
  auto normal_stun = stun_ticks();
  put(arena + 0x18, 2);
  auto fast_stun = stun_ticks();
  check(normal_stun == 15 && fast_stun == normal_stun,
        "Verified biped countdown kernel changed");
  const float gravity = std::bit_cast<float>(REX_LOAD_U32(0x8347A260));
  REX_STORE_U32(0x834B38C8, arena + 0x3000); // empty data array
  REX_STORE_U32(0x837E78E0, 0);
  struct Motion {
    float x, z, vz_per_second;
  };
  auto airborne = [&](int hz, bool normalize_units) {
    uint32_t physics = arena + 0x4000;
    std::memset(base + physics, 0, 0xD0);
    float step = normalize_units ? 30.f / hz : 1.f;
    // Convert all inputs of this isolated no-collision kernel. A playable
    // mode must also convert producers, consumers, responses and timers.
    put(0x8347A260, gravity * step * step);
    REX_STORE_U32(physics, 0xFFFFFFFFu);
    REX_STORE_U16(physics + 4, 0x41);           // airborne + no collision
    REX_STORE_U32(physics + 0x90, 0xFFFFFFFFu); // no support surface
    put(physics + 0x14, 1);                     // facing +X
    put(physics + 0x10, 1000);
    put(physics + 0x2C, step / 30); // one world unit per second
    put(physics + 0x3C, step / 30);
    put(physics + 0x54, 1);
    put(physics + 0x58, .25f);
    for (int i = 0; i < hz; ++i) {
      PPCContext ctx{};
      ctx.fpscr.InitHost();
      ctx.r1.u32 = arena + 0x3F000;
      ctx.r3.u32 = physics;
      sub_82D36520(ctx, base);
      std::memcpy(base + physics + 8, base + physics + 0xAC, 12);
      std::memcpy(base + physics + 0x2C, base + physics + 0xB8, 12);
    }
    auto get = [&](uint32_t p) {
      return std::bit_cast<float>(REX_LOAD_U32(p));
    };
    return Motion{get(physics + 8), get(physics + 0x10),
                  get(physics + 0x34) * hz};
  };
  auto motion30 = airborne(30, true), naive60 = airborne(60, false);
  auto motion60 = airborne(60, true), motion120 = airborne(120, true);
  check(std::abs(motion30.x - 1) < 1e-4f && std::abs(naive60.x - 2) < 1e-4f,
        "Actual biped motion did not expose the unconverted tick-unit speedup");
  for (auto sample : {motion60, motion120})
    check(std::abs(sample.x - motion30.x) < 1e-4f &&
              std::abs(sample.vz_per_second - motion30.vz_per_second) < 1e-4f,
          "Airborne unit conversion changed real-time speed or gravity");
  const float analytical_z = 1000.f - gravity * 900.f / 2.f;
  check(std::abs(motion60.z - analytical_z) <
                std::abs(motion30.z - analytical_z) &&
            std::abs(motion120.z - analytical_z) <
                std::abs(motion60.z - analytical_z),
        "Higher-rate airborne integration did not converge toward ballistic "
        "motion");
  put(0x8347A260, gravity);
  auto before_steps = XboxNativePhysicsStepCount();
  rex::cvar::SetFlagByName("native_biped_physics_hz", "60");
  auto integrated60 = airborne(30, true);
  auto steps60 = XboxNativePhysicsStepCount() - before_steps;
  before_steps = XboxNativePhysicsStepCount();
  rex::cvar::SetFlagByName("native_biped_physics_hz", "120");
  auto integrated120 = airborne(30, true);
  auto steps120 = XboxNativePhysicsStepCount() - before_steps;
  check(steps60 == 60 && steps120 == 120,
        "Playable physics hook did not execute the requested substeps");
  for (auto sample : {integrated60, integrated120})
    check(std::abs(sample.x - motion30.x) < 1e-4f &&
              std::abs(sample.vz_per_second - motion30.vz_per_second) < 1e-4f,
          "Integrated physics substeps changed speed or gravity");
  rex::cvar::SetFlagByName("native_biped_physics_hz", original_hz);
  std::ofstream receipt(directory / "simulation-timing.json");
  receipt << std::setprecision(9);
  receipt << "{\n  \"game_simulation_modified\": false,\n"
             "  \"scheduler_function\": \"0x822D1D80\",\n"
             "  \"biped_countdown_function\": \"0x82D36470\",\n"
             "  \"measurement_seconds\": 2,\n  \"baseline_ticks\": [";
  for (size_t i = 0; i < baseline.size(); ++i)
    receipt << (i ? ", " : "") << baseline[i];
  receipt << "],\n  \"render_hz\": [30, 60, 120, 240],\n"
          << "  \"accelerated_scheduler_ticks\": " << twice << ",\n"
          << "  \"biped_countdown_ticks\": " << unsigned(normal_stun)
          << ",\n"
             "  \"countdown_seconds_at_30hz\": 0.5,\n"
             "  \"countdown_seconds_at_60hz_without_conversion\": 0.25,\n"
          << "  \"airborne_physics_function\": \"0x82D36520\",\n"
          << "  \"airborne_baseline_30hz_x_after_1s\": " << motion30.x << ",\n"
          << "  \"airborne_unconverted_60hz_x_after_1s\": " << naive60.x
          << ",\n"
          << "  \"airborne_converted_60hz_x_after_1s\": " << motion60.x << ",\n"
          << "  \"airborne_converted_120hz_x_after_1s\": " << motion120.x
          << ",\n"
          << "  \"gravity_baseline_velocity_after_1s\": "
          << motion30.vz_per_second << ",\n"
          << "  \"gravity_converted_60hz_velocity_after_1s\": "
          << motion60.vz_per_second << ",\n"
          << "  \"gravity_converted_120hz_velocity_after_1s\": "
          << motion120.vz_per_second << ",\n"
          << "  \"gravity_unconverted_60hz_velocity_after_1s\": "
          << naive60.vz_per_second << ",\n"
          << "  \"height_30hz_after_1s\": " << motion30.z << ",\n"
          << "  \"height_60hz_after_1s\": " << motion60.z << ",\n"
          << "  \"height_120hz_after_1s\": " << motion120.z << ",\n"
          << "  \"analytical_height_after_1s\": " << analytical_z << ",\n"
          << "  \"playable_biped_substeps_60hz\": " << steps60 << ",\n"
          << "  \"playable_biped_substeps_120hz\": " << steps120 << ",\n"
          << "  \"integrated_60hz_x_after_1s\": " << integrated60.x << ",\n"
          << "  \"integrated_120hz_x_after_1s\": " << integrated120.x << ",\n"
          << "  \"full_simulation_unlock\": \"not_implemented\"\n}\n";
  receipt.close();
  check(bool(receipt), "Cannot save native timing evidence");
  std::fprintf(
      stderr,
      "check: actual scheduler ticks at 30/60/120/240 FPS = %d/%d/%d/%d in 2s; "
      "accelerated=%d; biped countdown=%u ticks (unchanged)\n",
      baseline[0], baseline[1], baseline[2], baseline[3], twice,
      unsigned(normal_stun));
  std::fprintf(
      stderr,
      "check: actual airborne physics X after 1s: 30Hz=%f naive60=%f "
      "converted60=%f converted120=%f; converted gravity velocities=%f/%f/%f\n",
      motion30.x, naive60.x, motion60.x, motion120.x, motion30.vz_per_second,
      motion60.vz_per_second, motion120.vz_per_second);
}
