#include "rex_physics.h"
#include "rex_animation.h"
#include XBOX_NATIVE_PCH
#include <algorithm>
#include <array>
#include <atomic>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstring>
#include <rex/cvar.h>
#include <rex/logging.h>

extern "C" REX_FUNC(sub_82D36520);
REXCVAR_DEFINE_INT32(native_biped_physics_hz, 60, "PC",
                     "Biped collision/physics substeps: 30, 60 or 120 Hz; game "
                     "logic remains 30 Hz");
namespace {
thread_local bool stepping = false;
thread_local float force_scale = 1;
std::atomic<uint64_t> step_count{0};
struct MathPolicy {
  using Platform = PPCFPSCRRegister::Platform;
  uint32_t saved = Platform::getcsr();
  MathPolicy() {
    auto control = saved & ~uint32_t(Platform::RoundMaskVal);
    Platform::InitHostExceptions(control);
    Platform::setcsr(control);
  }
  ~MathPolicy() { Platform::setcsr(saved); }
};
} // namespace
uint64_t XboxNativePhysicsStepCount() { return step_count.load(); }
void XboxNativeBipedForce(PPCContext &ctx) {
  if (!stepping)
    return;
  MathPolicy policy;
  ctx.f0.f64 *= force_scale;
}
bool XboxNativeBipedSubsteps(PPCContext &ctx, uint8_t *base) {
  if (stepping || XboxNativeCinematicActive(base))
    return false;
  int hz = std::stoi(rex::cvar::GetFlagByName("native_biped_physics_hz"));
  int steps = hz == 120 ? 4 : hz == 60 ? 2 : 1;
  if (steps == 1)
    return false;
  uint32_t p = ctx.r3.u32;
  if (!p)
    return false;
  // Parameters verified in both biped producers and the 82D36520 kernel.
  // Preserve the original tick's inputs; only final physics outputs escape.
  constexpr uint32_t fields[] = {8,    12,   16,   0x2C, 0x30, 0x34, 0x38,
                                 0x3C, 0x40, 0x44, 0x4C, 0x50, 0x5C, 0x90};
  std::array<uint32_t, std::size(fields)> original;
  for (size_t i = 0; i < original.size(); ++i)
    original[i] = REX_LOAD_U32(p + fields[i]);
  uint16_t original_flags = REX_LOAD_U16(p + 4), pulse_flags = 0;
  float peak_landing = 0, peak_collision = 0;
  auto get = [&](uint32_t off) {
    return std::bit_cast<float>(REX_LOAD_U32(p + off));
  };
  auto put = [&](uint32_t off, float value) {
    REX_STORE_U32(p + off, std::bit_cast<uint32_t>(value));
  };
  float ratio = 1.f / steps;
  {
    MathPolicy policy;
    for (uint32_t off :
         {0x2Cu, 0x30u, 0x34u, 0x38u, 0x3Cu, 0x40u, 0x44u, 0x5Cu})
      put(off, get(off) * ratio);
    for (uint32_t off : {0x4Cu, 0x50u})
      put(off, get(off) * ratio * ratio);
  }
  struct Scope {
    Scope(float ratio) {
      stepping = true;
      force_scale = ratio * ratio;
    }
    ~Scope() {
      stepping = false;
      force_scale = 1;
    }
  } scope(ratio);
  for (int i = 0; i < steps; ++i) {
    put(0xC4, 0);
    put(0xC8, 0);
    ctx.r3.u32 = p;
    sub_82D36520(ctx, base);
    ++step_count;
    uint16_t flags = REX_LOAD_U16(p + 0xA0);
    pulse_flags |= flags & ~uint16_t(3);
    {
      MathPolicy policy;
      peak_landing = std::max(peak_landing, get(0xC4));
      peak_collision = std::max(peak_collision, get(0xC8));
    }
    if (i + 1 < steps) {
      std::memcpy(base + p + 8, base + p + 0xAC, 12);
      std::memcpy(base + p + 0x2C, base + p + 0xB8, 12);
      REX_STORE_U16(p + 4, (original_flags & ~uint16_t(3)) | (flags & 3));
      REX_STORE_U32(p + 0x90, REX_LOAD_U32(p + 0xA4));
    }
  }
  {
    MathPolicy policy;
    for (uint32_t off : {0xB8u, 0xBCu, 0xC0u})
      put(off, get(off) * steps);
    put(0xC4, peak_landing * steps);
    put(0xC8, peak_collision * steps);
  }
  REX_STORE_U16(p + 0xA0, REX_LOAD_U16(p + 0xA0) | pulse_flags);
  REX_STORE_U16(p + 4, original_flags);
  for (size_t i = 0; i < original.size(); ++i)
    REX_STORE_U32(p + fields[i], original[i]);
  static thread_local auto last = std::chrono::steady_clock::time_point{};
  auto now = std::chrono::steady_clock::now();
  if (now - last > std::chrono::seconds(1) &&
      rex::cvar::GetFlagByName("native_input_probe") == "true") {
    REXLOG_INFO(
        "[native-physics] biped_hz={} steps_per_tick={} total_substeps={}", hz,
        steps, step_count.load());
    last = now;
  }
  return true;
}
