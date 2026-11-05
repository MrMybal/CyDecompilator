#include "rex_animation.h"
#include "rex_menu_bridge.h"
#include "rex_rt_api.h"
#include XBOX_NATIVE_PCH
#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <mutex>
#include <rex/cvar.h>
#include <rex/logging.h>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

extern "C" REX_FUNC(sub_82D14D80);
extern "C" REX_FUNC(sub_822DFBF0);

REXCVAR_DEFINE_BOOL(
    native_interpolate_animations, true, "PC",
    "Interpolate exported Halo animation poses between simulation ticks");
REXCVAR_DEFINE_BOOL(native_interpolate_cinematics, true, "PC",
                    "Interpolate cinematic render cameras between game ticks");
REXCVAR_DEFINE_BOOL(
    native_interpolate_vehicles, true, "PC",
    "Interpolate vehicle poses and the seated player's follow camera");
REXCVAR_DEFINE_BOOL(native_sprint_weapon_animation, true, "PC",
                    "Subtle first-person weapon movement while sprinting");
namespace {
using Clock = std::chrono::steady_clock;
using Matrix = std::array<float, 13>;
using Quaternion = std::array<float, 4>;
struct RenderFloatScope {
  using Platform = PPCFPSCRRegister::Platform;
  uint32_t saved = Platform::getcsr();
  RenderFloatScope() {
    uint32_t control = saved & ~uint32_t(Platform::RoundMaskVal);
    Platform::InitHostExceptions(control);
    Platform::setcsr(control);
  }
  ~RenderFloatScope() { Platform::setcsr(saved); }
};
float load_float(uint8_t *base, uint32_t address) {
  return std::bit_cast<float>(REX_LOAD_U32(address));
}
void normalize(Quaternion &q) {
  float norm = 0;
  for (float v : q)
    norm += v * v;
  float inv = 1.f / std::sqrt(norm);
  for (float &v : q)
    v *= inv;
}
Quaternion rotation(const Matrix &m) {
  Quaternion q{};
  float trace = m[1] + m[5] + m[9];
  if (trace > 0) {
    float s = std::sqrt(trace + 1.f) * 2.f;
    q = {(m[8] - m[6]) / s, (m[3] - m[7]) / s, (m[4] - m[2]) / s, .25f * s};
  } else {
    int i = m[1] > m[5] ? 0 : 1;
    if (m[9] > m[1 + i * 4])
      i = 2;
    int j = (i + 1) % 3, k = (j + 1) % 3;
    auto r = [&](int row, int col) { return m[1 + row * 3 + col]; };
    float s = std::sqrt(std::max(0.f, 1.f + r(i, i) - r(j, j) - r(k, k))) * 2.f;
    q[i] = .25f * s;
    q[j] = (r(i, j) + r(j, i)) / s;
    q[k] = (r(i, k) + r(k, i)) / s;
    q[3] = (r(k, j) - r(j, k)) / s;
  }
  normalize(q);
  return q;
}
Quaternion blend_rotation(Quaternion a, Quaternion b, float t) {
  float d = 0;
  for (int i = 0; i < 4; ++i)
    d += a[i] * b[i];
  if (d < 0) {
    for (float &v : b)
      v = -v;
    d = -d;
  }
  float x = 1 - t, y = t;
  if (d < .9995f) {
    float angle = std::acos(std::clamp(d, -1.f, 1.f));
    float s = std::sin(angle);
    x = std::sin((1 - t) * angle) / s;
    y = std::sin(t * angle) / s;
  }
  Quaternion q;
  for (int i = 0; i < 4; ++i)
    q[i] = a[i] * x + b[i] * y;
  normalize(q);
  return q;
}
Matrix interpolate(const Matrix &a, const Matrix &b, float t) {
  t = std::clamp(t, 0.f, 1.f);
  if (t == 0)
    return a;
  if (t == 1)
    return b;
  auto q = blend_rotation(rotation(a), rotation(b), t);
  float x = q[0], y = q[1], z = q[2], w = q[3];
  Matrix m{a[0] + (b[0] - a[0]) * t,
           1 - 2 * (y * y + z * z),
           2 * (x * y - z * w),
           2 * (x * z + y * w),
           2 * (x * y + z * w),
           1 - 2 * (x * x + z * z),
           2 * (y * z - x * w),
           2 * (x * z - y * w),
           2 * (y * z + x * w),
           1 - 2 * (x * x + y * y),
           0,
           0,
           0};
  for (int i = 10; i < 13; ++i)
    m[i] = a[i] + (b[i] - a[i]) * t;
  return m;
}
bool valid(const Matrix &m) {
  for (float v : m)
    if (!std::isfinite(v))
      return false;
  if (m[0] < 0 || m[0] > 100)
    return false;
  for (int row = 0; row < 3; ++row) {
    float d = 0;
    for (int c = 0; c < 3; ++c)
      d += m[1 + row * 3 + c] * m[1 + row * 3 + c];
    if (d < .8f || d > 1.2f)
      return false;
  }
  return true;
}
float distance2(const Matrix &a, const Matrix &b) {
  float d = 0;
  for (int i = 10; i < 13; ++i) {
    float v = a[i] - b[i];
    d += v * v;
  }
  return d;
}
struct History {
  uint32_t tick = 0, tag = 0;
  std::vector<Matrix> previous, current;
  Clock::time_point seen{};
  bool ready = false;
  bool cinematic = false;
};
std::mutex history_mutex;
std::unordered_map<uint64_t, History> histories;
uint64_t exports = 0, blended = 0;
uint32_t world_trace_samples = 0, fp_trace_samples = 0;
uint32_t classic_trace_samples = 0;
uint32_t rejected_pose_samples = 0;
Clock::time_point last_log{};
using LocalPose = std::array<float, 8>;
struct FirstPersonHistory {
  uint32_t tick = 0, weapon = 0, graph = 0;
  std::vector<LocalPose> previous, current;
  Clock::time_point seen{};
  bool ready = false;
};
FirstPersonHistory first_person[2];
struct SprintVisual {
  Clock::time_point seen{};
  float amount = 0, phase = 0;
};
SprintVisual sprint_visual[2];
using CameraPose = std::array<float, 10>; // position, forward, up, vertical FOV
struct CameraHistory {
  CameraPose previous{}, current{};
  uint32_t tick = 0;
  uint16_t player = 0;
  uint32_t vehicle = 0xFFFFFFFFu;
  bool cinematic = false;
  bool ready = false;
  Clock::time_point seen{};
};
std::unordered_map<uint32_t, CameraHistory> camera_histories;
uint32_t ObjectDatum(uint8_t *base, uint32_t handle) {
  if (handle == 0xFFFFFFFFu || (handle & 0xFFFFu) >= 2048)
    return 0;
  uint32_t table = REX_LOAD_U32(0x834B38CC);
  if (!table)
    return 0;
  uint32_t entries = REX_LOAD_U32(table + 0x34);
  if (!entries)
    return 0;
  uint32_t entry = entries + (handle & 0xFFFFu) * 12;
  return REX_LOAD_U16(entry) == (handle >> 16) ? REX_LOAD_U32(entry + 8) : 0;
}
uint32_t LocalPlayerUnit(uint8_t *base, uint16_t local_player) {
  if (local_player > 1)
    return 0;
  // 822DB338 maps local-player index to the full player datum handle.
  uint32_t mapping = REX_LOAD_U32(0x834B38C4);
  uint32_t table = REX_LOAD_U32(0x834B38C8);
  if (!mapping || !table)
    return 0;
  uint32_t player = REX_LOAD_U32(mapping + (local_player + 1) * 4);
  if (player == 0xFFFFFFFFu || (player & 0xFFFFu) >= 16)
    return 0;
  uint32_t entries = REX_LOAD_U32(table + 0x34);
  if (!entries)
    return 0;
  uint32_t datum = entries + (player & 0xFFFFu) * 512;
  if (REX_LOAD_U16(datum) != (player >> 16))
    return 0;
  uint32_t unit = ObjectDatum(base, REX_LOAD_U32(datum + 0x34));
  if (!unit || REX_LOAD_U16(unit + 0xB4) != 0)
    return 0;
  return unit;
}
uint32_t SeatedVehicle(uint8_t *base, uint16_t local_player) {
  uint32_t unit = LocalPlayerUnit(base, local_player);
  if (!unit)
    return 0xFFFFFFFFu;
  uint32_t vehicle = REX_LOAD_U32(unit + 0x11C);
  uint32_t parent = ObjectDatum(base, vehicle);
  return parent && REX_LOAD_U16(parent + 0xB4) == 1 ? vehicle : 0xFFFFFFFFu;
}
uint64_t fp_exports = 0, fp_blended = 0;
Clock::time_point fp_log{};
thread_local XboxNativeClassicDraw *classic_draw = nullptr;
} // namespace
bool XboxNativeCinematicActive(uint8_t *base) {
  // cinematic_in_progress, 822D4BA0: globals pointer, then byte +9.
  uint32_t cinematic = REX_LOAD_U32(0x83770310);
  return cinematic && REX_LOAD_U8(cinematic + 9) != 0;
}
XboxNativeCinematicCamera::XboxNativeCinematicCamera(PPCContext &ctx,
                                                     uint8_t *memory)
    : base(memory), window(ctx.r4.u32 ? ctx.r3.u32 : 0) {}
XboxNativeCinematicCamera::~XboxNativeCinematicCamera() {
  if (!window)
    return;
  RenderFloatScope floating_point_policy;
  struct PublishProjection {
    uint8_t *base;
    uint32_t camera;
    ~PublishProjection() {
      int height = int16_t(REX_LOAD_U16(camera + 0x30)) -
                   int16_t(REX_LOAD_U16(camera + 0x2C));
      int width = int16_t(REX_LOAD_U16(camera + 0x32)) -
                  int16_t(REX_LOAD_U16(camera + 0x2E));
      if (width > 0 && height > 0)
        XboxNativeRtProjection(load_float(base, camera + 0x28),
                               float(width) / height);
    }
  } publish{base, window + 0x58};
  std::lock_guard lock(history_mutex);
  bool cinematic = XboxNativeCinematicActive(base);
  uint16_t player = REX_LOAD_U16(window);
  uint32_t vehicle = cinematic ? 0xFFFFFFFFu : SeatedVehicle(base, player);
  bool interpolate =
      cinematic
          ? rex::cvar::GetFlagByName("native_interpolate_cinematics") == "true"
          : vehicle != 0xFFFFFFFFu &&
                rex::cvar::GetFlagByName("native_interpolate_vehicles") ==
                    "true";
  if (!interpolate || REX_LOAD_U8(0x834B38D0)) {
    camera_histories.erase(window);
    return;
  }
  // 822CAB58 writes a 0x54-byte rasterizer camera at window+0x58, then
  // copies it to window+4. Observer position/forward/up remain authoritative.
  uint32_t time = REX_LOAD_U32(0x8376FAEC);
  if (!time)
    return;
  uint32_t tick = REX_LOAD_U32(time + 0xC);
  float alpha = std::clamp(load_float(base, time + 0x1C) * 30.f, 0.f, 1.f);
  CameraPose sample{};
  for (int i = 0; i < 10; ++i) {
    sample[i] = load_float(base, window + 0x58 + (i == 9 ? 0x28 : i * 4));
    if (!std::isfinite(sample[i]))
      return;
  }
  if (!std::isfinite(alpha) || sample[9] <= .05f || sample[9] >= 3.1f)
    return;
  if (camera_histories.size() > 16)
    camera_histories.clear();
  auto &h = camera_histories[window];
  auto now = Clock::now();
  float displacement = 0, direction = 0;
  for (int i = 0; i < 3; ++i) {
    float d = sample[i] - h.current[i];
    displacement += d * d;
    direction += sample[i + 3] * h.current[i + 3];
  }
  if (now - h.seen > std::chrono::milliseconds(250) || h.player != player ||
      h.vehicle != vehicle || h.cinematic != cinematic ||
      (tick != h.tick && tick != h.tick + 1) || displacement > 1024.f ||
      direction < .5f || std::abs(sample[9] - h.current[9]) > .3f) {
    h.current = h.previous = sample;
    h.tick = tick;
    h.player = player;
    h.vehicle = vehicle;
    h.cinematic = cinematic;
    h.ready = false;
  } else if (tick != h.tick) {
    h.previous = h.current;
    h.current = sample;
    h.tick = tick;
    h.ready = true;
  }
  h.seen = now;
  if (!h.ready)
    return;
  CameraPose rendered{};
  for (int i = 0; i < 10; ++i)
    rendered[i] = h.previous[i] + (h.current[i] - h.previous[i]) * alpha;
  // Normalize the interpolated frame and remove the up/forward projection.
  auto normalize_vector = [&](int offset) {
    float norm = 0;
    for (int i = 0; i < 3; ++i)
      norm += rendered[offset + i] * rendered[offset + i];
    if (norm < .1f)
      return false;
    for (int i = 0; i < 3; ++i)
      rendered[offset + i] /= std::sqrt(norm);
    return true;
  };
  if (!normalize_vector(3))
    return;
  float dot = 0;
  for (int i = 0; i < 3; ++i)
    dot += rendered[3 + i] * rendered[6 + i];
  for (int i = 0; i < 3; ++i)
    rendered[6 + i] -= dot * rendered[3 + i];
  if (!normalize_vector(6))
    return;
  for (uint32_t camera : {window + 4, window + 0x58})
    for (int i = 0; i < 10; ++i)
      REX_STORE_U32(camera + (i == 9 ? 0x28 : i * 4),
                    std::bit_cast<uint32_t>(rendered[i]));
}
void XboxNativeAnimationResetTrace() {
  std::lock_guard lock(history_mutex);
  world_trace_samples = classic_trace_samples = fp_trace_samples =
      rejected_pose_samples = 0;
}
XboxNativeClassicDraw::XboxNativeClassicDraw(PPCContext &context)
    : ctx(context), stack(ctx.r1.u32), scratch(stack - 0xD40 + 0x40),
      parent(classic_draw) {
  // Verified three register arguments at 82CB5688; no incoming stack args.
  // Its own prologue and nested calls allocate below this new stack pointer.
  ctx.r1.u32 -= 0xD40;
  classic_draw = this;
}
XboxNativeClassicDraw::~XboxNativeClassicDraw() {
  classic_draw = parent;
  ctx.r1.u32 = stack;
}
XboxNativeClassicNodes::XboxNativeClassicNodes(PPCContext &context,
                                               uint8_t *memory)
    : ctx(context), base(memory), object(ctx.r3.u32), caller(ctx.lr) {}
XboxNativeClassicNodes::~XboxNativeClassicNodes() {
  if (!classic_draw || (caller != 0x82CB58DC && caller != 0x82CB596C) ||
      object == 0xFFFFFFFFu || !ctx.r3.u32)
    return;
  uint32_t table = REX_LOAD_U32(0x834B38CC), tags = REX_LOAD_U32(0x834B38C0);
  if (!table || !tags || (object & 0xFFFF) >= 2048)
    return;
  uint32_t entries = REX_LOAD_U32(table + 0x34);
  if (!entries)
    return;
  uint32_t entry = entries + (object & 0xFFFF) * 12;
  if (REX_LOAD_U16(entry) != (object >> 16))
    return;
  uint32_t datum = REX_LOAD_U32(entry + 8);
  if (!datum || ctx.r3.u32 != datum + int16_t(REX_LOAD_U16(datum + 0x1F2)))
    return;
  uint32_t tag = REX_LOAD_U32(datum);
  if (tag == 0xFFFFFFFFu)
    return;
  uint32_t definition = REX_LOAD_U32(tags + (tag & 0xFFFF) * 32 + 0x14);
  if (!definition)
    return;
  uint32_t model = REX_LOAD_U32(definition + 0x34);
  if (model == 0xFFFFFFFFu)
    return;
  uint32_t model_data = REX_LOAD_U32(tags + (model & 0xFFFF) * 32 + 0x14);
  if (!model_data)
    return;
  uint32_t count = REX_LOAD_U32(model_data + 0xB8);
  if (!count || count > 64 || REX_LOAD_U16(datum + 0x1F0) < count * 52)
    return;
  uint32_t scratch = classic_draw->scratch;
  std::memcpy(base + scratch, base + ctx.r3.u32, count * 52);
  PPCContext copy{};
  copy.r3.u32 = object;
  copy.r4.u32 = scratch;
  {
    XboxNativePoseExport pose(copy, base, false, true);
    copy.r3.u32 = count;
  }
  static thread_local auto last_trace = Clock::time_point{};
  auto now = Clock::now();
  if (REX_LOAD_U16(datum + 0xB4) == 0 &&
      now - last_trace > std::chrono::seconds(1) &&
      rex::cvar::GetFlagByName("native_input_probe") == "true") {
    REXLOG_INFO("[native-classic-draw] object={:08X} nodes={} source={:08X} "
                "render={:08X} owner={:08X}",
                object, count, ctx.r3.u32, scratch,
                REX_LOAD_U32(datum + 0x218));
    last_trace = now;
  }
  ctx.r3.u64 = scratch;
}
XboxNativePoseExport::XboxNativePoseExport(PPCContext &context, uint8_t *memory,
                                           bool root_matrix, bool classic_path)
    : ctx(context), base(memory), object(ctx.r3.u32), output(ctx.r4.u32),
      root(root_matrix), classic(classic_path) {}
XboxNativePoseExport::~XboxNativePoseExport() {
  RenderFloatScope floating_point_policy;
  uint32_t count = root ? 1 : ctx.r3.u32;
  if (!count || count > 64 || object == 0xFFFFFFFFu || !output)
    return;
  // Exact-image globals and object table layout verified in 822E3E30,
  // 82C54908, 82C547F0 and 82C695D0. The table carries generation IDs.
  uint32_t time = REX_LOAD_U32(0x8376FAEC), table = REX_LOAD_U32(0x834B38CC);
  if (!time || !table)
    return;
  uint32_t entries = REX_LOAD_U32(table + 0x34), index = object & 0xFFFF;
  if (index >= 2048 || !entries)
    return;
  uint32_t entry = entries + index * 12;
  if (REX_LOAD_U16(entry) != (object >> 16))
    return;
  uint32_t datum = REX_LOAD_U32(entry + 8);
  if (!datum)
    return;
  uint32_t tag = REX_LOAD_U32(datum), tick = REX_LOAD_U32(time + 0xC);
  float alpha = std::clamp(load_float(base, time + 0x1C) * 30.f, 0.f, 1.f);
  if (!std::isfinite(alpha))
    return;
  auto now = Clock::now();
  std::lock_guard lock(history_mutex);
  auto &h = histories[(uint64_t(object) << 2) | root | (classic ? 2 : 0)];
  if (histories.size() > 4096) {
    histories.clear();
    return;
  }
  std::vector<Matrix> sample(count);
  for (uint32_t n = 0; n < count; ++n) {
    for (int i = 0; i < 13; ++i)
      sample[n][i] = load_float(base, output + n * 52 + i * 4);
    if (!valid(sample[n])) {
      if (!root && rejected_pose_samples < 8 &&
          rex::cvar::GetFlagByName("native_input_probe") == "true") {
        REXLOG_INFO("[native-pose-rejected] object={:08X} nodes={} index={} "
                    "scale={} matrix={},{},{},{},{},{},{},{},{}",
                    object, count, n, sample[n][0], sample[n][1], sample[n][2],
                    sample[n][3], sample[n][4], sample[n][5], sample[n][6],
                    sample[n][7], sample[n][8], sample[n][9]);
        ++rejected_pose_samples;
      }
      return;
    }
  }
  bool cinematic = XboxNativeCinematicActive(base);
  bool vehicle = REX_LOAD_U16(datum + 0xB4) == 1;
  // Scripted ships may move farther than a walking unit's teleport threshold.
  float snap_distance2 = cinematic ? 4096.f : vehicle ? 256.f : 6.25f;
  if (h.current.empty() || h.tag != tag || h.current.size() != count ||
      h.cinematic != cinematic ||
      now - h.seen > std::chrono::milliseconds(250) ||
      (h.tick != tick && tick != h.tick + 1) ||
      distance2(h.current[0], sample[0]) > snap_distance2) {
    h.current = sample;
    h.previous = sample;
    h.tick = tick;
    h.tag = tag;
    h.ready = false;
    h.cinematic = cinematic;
  } else if (h.tick != tick) {
    h.previous = std::move(h.current);
    h.current = sample;
    h.tick = tick;
    h.ready = true;
  }
  h.seen = now;
  ++exports;
  if (h.ready && rex::cvar::GetFlagByName(
                     vehicle ? "native_interpolate_vehicles"
                             : "native_interpolate_animations") == "true") {
    for (uint32_t n = 0; n < count; ++n) {
      auto m = interpolate(h.previous[n], h.current[n], alpha);
      for (int i = 0; i < 13; ++i)
        REX_STORE_U32(output + n * 52 + i * 4, std::bit_cast<uint32_t>(m[i]));
    }
    ++blended;
    if (root)
      ctx.r3.u64 = 1; // root copy may have compared equal before interpolation
    auto &trace_samples = classic ? classic_trace_samples : world_trace_samples;
    if (!root && trace_samples < 256 && alpha > .05f && alpha < .95f &&
        REX_LOAD_U16(datum + 0xB4) == 0 &&
        rex::cvar::GetFlagByName("native_input_probe") == "true") {
      for (uint32_t n = 0; n < count; ++n)
        if (distance2(h.previous[n], h.current[n]) > 1e-8f) {
          REXLOG_INFO(
              "[native-pose-sample] world object={:08X} tick={} node={} "
              "alpha={:.5f} previous_x={:.6f} current_x={:.6f} render_x={:.6f}",
              object, tick, n, alpha, h.previous[n][10], h.current[n][10],
              load_float(base, output + n * 52 + 40));
          std::string name;
          uint32_t tags = REX_LOAD_U32(0x834B38C0);
          uint32_t path =
              tags ? REX_LOAD_U32(tags + (tag & 0xFFFF) * 32 + 0x10) : 0;
          if (path && path < 0xFFFFFEFFu)
            for (int i = 0; i < 255; ++i) {
              char c = base[path + i];
              if (c < 32 || c > 126)
                break;
              name += c;
            }
          REXLOG_INFO(
              "[native-world-motion] path={} model={} object={:08X} "
              "owner={:08X} tick={} alpha={:.5f} position={:.6f},{:.6f},{:.6f} "
              "root_previous={:.6f},{:.6f},{:.6f} "
              "root_current={:.6f},{:.6f},{:.6f} "
              "root_render={:.6f},{:.6f},{:.6f}",
              classic ? "classic" : "saber", name, object,
              REX_LOAD_U32(datum + 0x218), tick, alpha,
              load_float(base, datum + 0x5C), load_float(base, datum + 0x60),
              load_float(base, datum + 0x64), h.previous[0][10],
              h.previous[0][11], h.previous[0][12], h.current[0][10],
              h.current[0][11], h.current[0][12], load_float(base, output + 40),
              load_float(base, output + 44), load_float(base, output + 48));
          ++trace_samples;
          break;
        }
    }
  }
  if (rex::cvar::GetFlagByName("native_input_probe") == "true" &&
      now - last_log > std::chrono::seconds(1)) {
    REXLOG_INFO("[native-animation] exports={} blended={} tick={} alpha={:.4f} "
                "object={:08X} nodes={} root={}",
                exports, blended, tick, alpha, object, count, root);
    exports = blended = 0;
    last_log = now;
  }
}
XboxNativeFirstPersonPose::XboxNativeFirstPersonPose(PPCContext &ctx,
                                                     uint8_t *memory)
    : base(memory) {
  RenderFloatScope floating_point_policy;
  // Only the final first-person pose-to-matrix call, after animation layers
  // and before the current camera transform. Other physics/math users of the
  // same conversion function must never see interpolated simulation poses.
  if (ctx.lr != 0x82C7A778)
    return;
  uint32_t fp = REX_LOAD_U32(0x837729FC), time = REX_LOAD_U32(0x8376FAEC),
           tags = REX_LOAD_U32(0x834B38C0);
  if (!fp || !time || !tags)
    return;
  uint32_t slot = REX_LOAD_U16(0x834B6968);
  if (slot > 1 || ctx.r5.u32 != fp + slot * 0x1EA0 + 0x8C)
    return;
  fp += slot * 0x1EA0;
  if (!REX_LOAD_U8(fp))
    return;
  uint32_t weapon = REX_LOAD_U32(fp + 8), graph = ctx.r3.u32;
  if (weapon == 0xFFFFFFFFu || graph == 0xFFFFFFFFu)
    return;
  uint32_t graph_data = REX_LOAD_U32(tags + (graph & 0xFFFF) * 32 + 0x14);
  if (!graph_data)
    return;
  uint32_t count = REX_LOAD_U32(graph_data + 0x68),
           tick = REX_LOAD_U32(time + 0xC);
  if (!count || count > 64)
    return;
  float alpha = std::clamp(load_float(base, time + 0x1C) * 30.f, 0.f, 1.f);
  if (!std::isfinite(alpha))
    return;
  std::vector<LocalPose> sample(count);
  for (uint32_t n = 0; n < count; ++n) {
    float norm = 0;
    for (int i = 0; i < 8; ++i) {
      float v = load_float(base, ctx.r5.u32 + n * 32 + i * 4);
      if (!std::isfinite(v))
        return;
      sample[n][i] = v;
      if (i < 4)
        norm += v * v;
    }
    if (norm < .8f || norm > 1.2f)
      return;
  }
  auto now = Clock::now();
  std::lock_guard lock(history_mutex);
  auto &visual = sprint_visual[slot];
  float dt = std::chrono::duration<float>(now - visual.seen).count();
  if (dt > .25f || dt < 0)
    visual.amount = 0;
  dt = std::clamp(dt, 0.f, .05f);
  visual.seen = now;
  uint32_t local_unit = LocalPlayerUnit(base, slot);
  // 82D39578 copies biped flags bit 0 at +4CC to the physics airborne bit.
  bool grounded = local_unit && !(REX_LOAD_U32(local_unit + 0x4CC) & 1u);
  bool running =
      grounded && slot == 0 && XboxNativeSprintActive() &&
      !XboxNativeCinematicActive(base) &&
      rex::cvar::GetFlagByName("native_sprint_weapon_animation") == "true";
  visual.amount +=
      ((running ? 1.f : 0.f) - visual.amount) * (1.f - std::exp(-dt * 14.f));
  visual.phase = std::fmod(visual.phase + dt * 11.f, 6.2831853f);
  if (!grounded) {
    visual.amount = 0;
    visual.phase = 0;
  }
  if (visual.amount > .001f && ctx.r4.u32 && ctx.r7.u32 && ctx.r8.u32) {
    std::array<float, 3> forward{}, up{}, side{};
    for (int i = 0; i < 3; ++i) {
      forward[i] = load_float(base, ctx.r7.u32 + i * 4);
      up[i] = load_float(base, ctx.r8.u32 + i * 4);
      if (!std::isfinite(forward[i]) || !std::isfinite(up[i]))
        return;
    }
    for (int i = 0; i < 3; ++i)
      side[i] = up[(i + 1) % 3] * forward[(i + 2) % 3] -
                up[(i + 2) % 3] * forward[(i + 1) % 3];
    float lateral = .008f * std::sin(visual.phase);
    float vertical = -.025f + .006f * std::cos(visual.phase * 2.f);
    for (int i = 0; i < 3; ++i)
      sprint_offset[i] = visual.amount * (side[i] * lateral + up[i] * vertical -
                                          forward[i] * .012f);
    output = ctx.r4.u32;
    this->count = count;
  }
  auto &h = first_person[slot];
  if (h.current.empty() || h.weapon != weapon || h.graph != graph ||
      h.current.size() != count ||
      now - h.seen > std::chrono::milliseconds(250) ||
      (h.tick != tick && tick != h.tick + 1)) {
    h.previous = sample;
    h.current = sample;
    h.tick = tick;
    h.weapon = weapon;
    h.graph = graph;
    h.ready = false;
  } else if (h.tick != tick) {
    h.previous = std::move(h.current);
    h.current = sample;
    h.tick = tick;
    h.ready = true;
  }
  h.seen = now;
  ++fp_exports;
  if (h.ready &&
      rex::cvar::GetFlagByName("native_interpolate_animations") == "true") {
    source = ctx.r5.u32;
    original.assign(base + source, base + source + count * 32);
    for (uint32_t n = 0; n < count; ++n) {
      auto &a = h.previous[n];
      auto &b = h.current[n];
      auto q = blend_rotation({a[0], a[1], a[2], a[3]},
                              {b[0], b[1], b[2], b[3]}, alpha);
      for (int i = 0; i < 8; ++i) {
        float v = i < 4 ? q[i] : a[i] + (b[i] - a[i]) * alpha;
        REX_STORE_U32(source + n * 32 + i * 4, std::bit_cast<uint32_t>(v));
      }
    }
    ++fp_blended;
    if (fp_trace_samples < 32 && alpha > .05f && alpha < .95f &&
        rex::cvar::GetFlagByName("native_input_probe") == "true") {
      for (uint32_t n = 0; n < count; ++n)
        if (std::abs(h.previous[n][4] - h.current[n][4]) > 1e-7f) {
          REXLOG_INFO(
              "[native-pose-sample] fp weapon={:08X} tick={} node={} "
              "alpha={:.5f} previous_x={:.6f} current_x={:.6f} render_x={:.6f}",
              weapon, tick, n, alpha, h.previous[n][4], h.current[n][4],
              load_float(base, source + n * 32 + 16));
          ++fp_trace_samples;
          break;
        }
    }
  }
  if (rex::cvar::GetFlagByName("native_input_probe") == "true" &&
      now - fp_log > std::chrono::seconds(1)) {
    REXLOG_INFO("[native-animation-fp] exports={} blended={} tick={} "
                "alpha={:.4f} weapon={:08X} nodes={}",
                fp_exports, fp_blended, tick, alpha, weapon, count);
    fp_exports = fp_blended = 0;
    fp_log = now;
  }
}
XboxNativeFirstPersonPose::~XboxNativeFirstPersonPose() {
  if (source && !original.empty())
    std::memcpy(base + source, original.data(), original.size());
  if (output && count) {
    RenderFloatScope floating_point_policy;
    // Translate the completed bone matrices together, after conversion. This
    // keeps the arms/weapon rigid and never moves the camera or firing origin.
    for (uint32_t n = 0; n < count; ++n)
      for (int i = 0; i < 3; ++i) {
        uint32_t address = output + n * 52 + 40 + i * 4;
        float value = load_float(base, address) + sprint_offset[i];
        REX_STORE_U32(address, std::bit_cast<uint32_t>(value));
      }
  }
}
void XboxNativeAnimationSelfTest() {
  Matrix a{1, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0},
      b{2, -1, 0, 0, 0, -1, 0, 0, 0, 1, 2, 4, 6};
  auto m = interpolate(a, b, .5f);
  if (!valid(m) || std::abs(m[10] - 1) > 1e-5 || std::abs(m[11] - 2) > 1e-5 ||
      std::abs(m[1]) > 1e-5 || std::abs(m[2] + 1) > 1e-5 || m[0] != 1.5f)
    throw std::runtime_error(
        "Pose interpolation failed rotation/translation/scale checks");
  if (interpolate(a, b, 0) != a || interpolate(a, b, 1) != b)
    throw std::runtime_error("Pose endpoints changed");
}
void XboxNativeAnimationIntegrationCheck(uint8_t *base, uint32_t arena) {
  std::fprintf(stderr, "check: animation math\n");
  XboxNativeAnimationSelfTest();
  std::fprintf(stderr, "check: animation render exports\n");
  auto check = [](bool ok, const char *reason) {
    if (!ok)
      throw std::runtime_error(reason);
  };
  auto put = [&](uint32_t p, float f) {
    REX_STORE_U32(p, std::bit_cast<uint32_t>(f));
  };
  uint32_t addresses[] = {0x8376FAEC, 0x834B38CC, 0x834B38C0, 0x837729FC};
  uint32_t saved[4];
  for (int i = 0; i < 4; ++i)
    saved[i] = REX_LOAD_U32(addresses[i]);
  auto saved_view = REX_LOAD_U16(0x834B6968);
  std::memset(base + arena, 0, 0x40000);
  uint32_t time = arena + 0x100, table = arena + 0x500,
           entries = arena + 0x1000, datum = arena + 0x9000;
  uint32_t tags = arena + 0x10000, graph = arena + 0x11000,
           nodes = arena + 0x12000, fp = arena + 0x14000;
  uint32_t output = arena + 0x1C000, camera = arena + 0x1D000;
  REX_STORE_U32(addresses[0], time);
  REX_STORE_U32(addresses[1], table);
  REX_STORE_U32(addresses[2], tags);
  REX_STORE_U32(addresses[3], fp);
  REX_STORE_U16(0x834B6968, 0);
  REX_STORE_U32(table + 0x34, entries);
  REX_STORE_U16(entries, 0xE26F);
  REX_STORE_U32(entries + 8, datum);
  REX_STORE_U32(datum, 0x1234);
  REX_STORE_U32(time + 0xC, 10);
  put(time + 0x1C, 1.f / 60.f);
  Matrix identity{1, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0};
  auto write_matrix = [&](Matrix m) {
    for (int i = 0; i < 13; ++i)
      put(output + i * 4, m[i]);
  };
  PPCContext ctx{};
  ctx.r3.u32 = 0xE26F0000;
  ctx.r4.u32 = output;
  write_matrix(identity);
  {
    XboxNativePoseExport export_pose(ctx, base, false);
    ctx.r3.u32 = 1;
  }
  REX_STORE_U32(time + 0xC, 11);
  auto moved = identity;
  moved[10] = 2;
  write_matrix(moved);
  ctx.r3.u32 = 0xE26F0000;
  PPCContext before = ctx;
  {
    XboxNativePoseExport export_pose(ctx, base, false);
    ctx.r3.u32 = 1;
    before.r3.u32 = 1;
  }
  check(std::abs(load_float(base, output + 40) - 1) < 1e-5,
        "Render matrix did not interpolate between two ticks");
  check(std::memcmp(&before, &ctx, sizeof(ctx)) == 0,
        "Pose export changed PPC registers");
  check(REX_LOAD_U32(datum) == 0x1234,
        "Pose export changed simulation object data");
  // Teleports and recycled object definitions must snap, never smear.
  REX_STORE_U32(time + 0xC, 12);
  moved[10] = 100;
  write_matrix(moved);
  ctx.r3.u32 = 0xE26F0000;
  {
    XboxNativePoseExport export_pose(ctx, base, false);
    ctx.r3.u32 = 1;
  }
  check(load_float(base, output + 40) == 100,
        "Teleport interpolated across the map");
  REX_STORE_U32(time + 0xC, 13);
  REX_STORE_U32(datum, 0x5678);
  moved[10] = 101;
  write_matrix(moved);
  ctx.r3.u32 = 0xE26F0000;
  {
    XboxNativePoseExport export_pose(ctx, base, false);
    ctx.r3.u32 = 1;
  }
  check(load_float(base, output + 40) == 101,
        "Recycled model reused old pose history");
  // Execute the REAL statically compiled first-person pose-to-matrix code.
  REX_STORE_U8(fp, 1);
  REX_STORE_U32(fp + 8, 0xABCD0001);
  REX_STORE_U32(tags + 32 + 0x14, graph);
  REX_STORE_U32(graph + 0x68, 1);
  REX_STORE_U32(graph + 0x6C, nodes);
  REX_STORE_U16(nodes + 0x20, 0xFFFF);
  REX_STORE_U16(nodes + 0x22, 0xFFFF);
  REX_STORE_U16(nodes + 0x24, 0xFFFF);
  put(camera + 12, 1);
  put(camera + 32, 1); // forward X and up Z
  put(fp + 0x8C + 12, 1);
  put(fp + 0x8C + 28, 1); // identity quaternion and unit scale
  auto convert = [&] {
    PPCContext call{};
    call.r1.u32 = arena + 0x3F000;
    call.lr = 0x82C7A778;
    call.fpscr.InitHost(); // Match a real guest thread's host exception policy.
    call.r3.u32 = 0x20001;
    call.r4.u32 = output;
    call.r5.u32 = fp + 0x8C;
    call.r6.u32 = camera;
    call.r7.u32 = camera + 12;
    call.r8.u32 = camera + 24;
    sub_82D14D80(call, base);
  };
  REX_STORE_U32(time + 0xC, 20);
  convert();
  std::fprintf(stderr, "check: actual FP identity conversion\n");
  REX_STORE_U32(time + 0xC, 21);
  put(fp + 0x8C + 16, 2);
  std::array<uint8_t, 32> authoritative;
  std::memcpy(authoritative.data(), base + fp + 0x8C, 32);
  convert();
  check(std::abs(load_float(base, output + 40) - 1) < 1e-5,
        "Real first-person converter did not consume the intermediate pose");
  check(std::memcmp(authoritative.data(), base + fp + 0x8C, 32) == 0,
        "First-person interpolation leaked into simulation state");
  // A second render in the same tick uses the original pose, not its result.
  put(time + 0x1C, .75f / 30);
  convert();
  check(std::abs(load_float(base, output + 40) - 1.5f) < 1e-5,
        "First-person rendering fed an interpolated pose back into history");
  check(std::memcmp(authoritative.data(), base + fp + 0x8C, 32) == 0,
        "Repeated render changed the source pose");
  rex::cvar::SetFlagByName("native_interpolate_animations", "false");
  convert();
  check(std::abs(load_float(base, output + 40) - 2) < 1e-5,
        "Disabled interpolation modified first-person output");
  rex::cvar::SetFlagByName("native_interpolate_animations", "true");
  // The classic draw gets a guest-addressable copy through the REAL getter;
  // callers performing collision or simulation queries keep the original.
  REX_STORE_U32(datum, 1);
  REX_STORE_U32(tags + 32 + 0x14, graph);
  REX_STORE_U32(graph + 0x34, 2);
  REX_STORE_U32(tags + 64 + 0x14, nodes);
  REX_STORE_U32(nodes + 0xB8, 1);
  REX_STORE_U16(datum + 0x1F0, 52);
  REX_STORE_U16(datum + 0x1F2, 0x300);
  auto classic = [&](float position, uint32_t caller) {
    for (int i = 0; i < 13; ++i)
      put(datum + 0x300 + i * 4, identity[i]);
    put(datum + 0x300 + 40, position);
    std::array<uint8_t, 52> authoritative_matrix;
    std::memcpy(authoritative_matrix.data(), base + datum + 0x300, 52);
    PPCContext call{};
    call.r1.u32 = arena + 0x3F000;
    call.r3.u32 = 0xE26F0000;
    call.lr = caller;
    call.fpscr.InitHost();
    auto original_stack = call.r1.u32;
    {
      XboxNativeClassicDraw draw(call);
      sub_822DFBF0(call, base);
      check(std::memcmp(authoritative_matrix.data(), base + datum + 0x300,
                        52) == 0,
            "Classic draw modified authoritative object matrices");
      if (caller == 0x82CB58DC || caller == 0x82CB596C)
        check(call.r3.u32 == draw.scratch,
              "Classic render getter did not return its copy");
      else
        check(call.r3.u32 == datum + 0x300,
              "Physics getter received render matrices");
    }
    check(call.r1.u32 == original_stack,
          "Classic draw changed the caller's stack");
    return load_float(base, call.r3.u32 + 40);
  };
  REX_STORE_U32(time + 0xC, 30);
  put(time + 0x1C, .5f / 30);
  classic(0, 0x82CB58DC);
  REX_STORE_U32(time + 0xC, 31);
  check(std::abs(classic(2, 0x82CB58DC) - 1) < 1e-5,
        "Classic enemy root position did not interpolate");
  put(time + 0x1C, .75f / 30);
  check(std::abs(classic(2, 0x82CB596C) - 1.5f) < 1e-5,
        "Classic second render did not advance between ticks");
  check(classic(2, 0x12345678) == 2, "Simulation query used interpolation");
  std::fprintf(stderr, "check: actual classic getter / intermediate root "
                       "positions / simulation isolation passed\n");
  for (int i = 0; i < 4; ++i)
    REX_STORE_U32(addresses[i], saved[i]);
  REX_STORE_U16(0x834B6968, saved_view);
  std::lock_guard lock(history_mutex);
  histories.clear();
  first_person[0] = {};
  first_person[1] = {};
  std::fprintf(stderr,
               "check: pose slerp / tick samples / teleport / model reuse / "
               "actual FP conversion / exact restoration passed\n");
}
