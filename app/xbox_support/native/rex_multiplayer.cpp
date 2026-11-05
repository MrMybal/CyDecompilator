// PC-only local players and direct UDP/System Link transport for native builds.
// clang-format off
// WinSock must precede windows.h, and BCrypt requires Windows type definitions.
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <bcrypt.h>
// clang-format on
#include "rex_multiplayer.h"
#include <array>
#include <atomic>
#include <chrono>
#include <fstream>
#include <imgui.h>
#include <mutex>
#include <rex/cvar.h>
#include <rex/hook.h>
#include <rex/input/device_assignment.h>
#include <rex/input/input_driver.h>
#include <rex/input/input_system.h>
#include <rex/runtime.h>
#include <rex/system/util/object_table.h>
#include <rex/system/xam/content_manager.h>
#include <rex/system/xsocket.h>
#include <rex/system/xthread.h>
#include <toml++/toml.hpp>
#include <unordered_map>

REXCVAR_DEFINE_UINT32(native_local_players, 1, "PC multiplayer",
                      "Number of offline campaign profiles (1-2)");
REXCVAR_DEFINE_BOOL(
    native_keyboard_player_one, true, "PC multiplayer",
    "Reserve player one for keyboard/mouse; first pad goes to player two");
REXCVAR_DEFINE_BOOL(native_direct_ip, false, "PC multiplayer",
                    "Enable the PC UDP/System Link adapter without Xbox Live");
REXCVAR_DEFINE_STRING(native_net_peer, "", "PC multiplayer",
                      "Direct IPv4 peer, optionally :port; empty hosts a game");
REXCVAR_DEFINE_STRING(
    native_net_address, "", "PC multiplayer",
    "Advertised local IPv4; empty selects the route to the peer");
REXCVAR_DEFINE_STRING(native_user_id, "", "PC multiplayer",
                      "Persistent local machine player ID, hexadecimal");

namespace {
using namespace rex;
using namespace rex::system;
using namespace rex::input;
using Clock = std::chrono::steady_clock;
std::filesystem::path user_root;
std::string settings_error;
std::atomic<unsigned> game_port{1000};
std::atomic<uint64_t> sent{0}, received{0};
std::array<std::atomic<int64_t>, 4> join_until{};
std::atomic<unsigned> virtual_pads{0};
std::atomic<unsigned> join_requested{0};
std::mutex key_mutex;
std::unordered_map<std::string, std::array<uint8_t, 16>> keys;
constexpr uint32_t kPadBase = 0x43594D00;
int64_t now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             Clock::now().time_since_epoch())
      .count();
}
void save_settings() {
  if (user_root.empty())
    return;
  try {
    std::filesystem::create_directories(user_root);
    auto temporary = user_root / "campaign-coop.toml.tmp";
    std::ofstream out(temporary, std::ios::trunc);
    toml::table config{
        {"local_players", int64_t(XboxNativeLocalPlayers())},
        {"keyboard_player_one", REXCVAR_GET(native_keyboard_player_one)},
        {"direct_ip", REXCVAR_GET(native_direct_ip)},
        {"peer", REXCVAR_GET(native_net_peer)},
        {"address", REXCVAR_GET(native_net_address)}};
    out << config;
    out.close();
    if (!out)
      throw std::runtime_error("Ecriture impossible");
    std::filesystem::rename(temporary, user_root / "campaign-coop.toml");
    settings_error.clear();
  } catch (const std::exception &error) {
    settings_error = error.what();
  }
}
uint16_t read16(const uint8_t *p) { return uint16_t(p[0]) << 8 | p[1]; }
uint32_t read32(const uint8_t *p) {
  return uint32_t(p[0]) << 24 | uint32_t(p[1]) << 16 | uint32_t(p[2]) << 8 |
         p[3];
}
void write16(uint8_t *p, uint16_t n) {
  p[0] = uint8_t(n >> 8);
  p[1] = uint8_t(n);
}
void write32(uint8_t *p, uint32_t n) {
  p[0] = uint8_t(n >> 24);
  p[1] = uint8_t(n >> 16);
  p[2] = uint8_t(n >> 8);
  p[3] = uint8_t(n);
}
uint32_t arg(PPCContext &c, uint8_t *base, unsigned index) {
  switch (index) {
  case 0:
    return c.r3.u32;
  case 1:
    return c.r4.u32;
  case 2:
    return c.r5.u32;
  case 3:
    return c.r6.u32;
  case 4:
    return c.r7.u32;
  case 5:
    return c.r8.u32;
  case 6:
    return c.r9.u32;
  case 7:
    return c.r10.u32;
  default:
    return read32(base + c.r1.u32 + 0x54 + (index - 8) * 8);
  }
}
void result(PPCContext &c, int value) { c.r3.s64 = value; }
bool random_bytes(void *p, size_t n) {
  return BCryptGenRandom(nullptr, static_cast<PUCHAR>(p), ULONG(n),
                         BCRYPT_USE_SYSTEM_PREFERRED_RNG) >= 0;
}
bool peer(sockaddr_in &address) {
  auto text = REXCVAR_GET(native_net_peer);
  auto colon = text.find(':');
  std::string ip = text.substr(0, colon);
  address = {};
  address.sin_family = AF_INET;
  if (InetPtonA(AF_INET, ip.c_str(), &address.sin_addr) != 1)
    return false;
  if (colon != std::string::npos) {
    try {
      auto port = std::stoul(text.substr(colon + 1));
      if (!port || port > 65535)
        return false;
      address.sin_port = htons(uint16_t(port));
    } catch (...) {
      return false;
    }
  }
  return true;
}
in_addr local_address() {
  in_addr out{};
  if (InetPtonA(AF_INET, REXCVAR_GET(native_net_address).c_str(), &out) == 1)
    return out;
  sockaddr_in remote{};
  if (!peer(remote)) {
    remote.sin_family = AF_INET;
    InetPtonA(AF_INET, "192.0.2.1", &remote.sin_addr);
  }
  remote.sin_port = htons(9);
  SOCKET probe = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
  if (probe != INVALID_SOCKET) {
    if (connect(probe, reinterpret_cast<sockaddr *>(&remote), sizeof(remote)) ==
        0) {
      sockaddr_in local{};
      int size = sizeof(local);
      if (getsockname(probe, reinterpret_cast<sockaddr *>(&local), &size) == 0)
        out = local.sin_addr;
    }
    closesocket(probe);
  }
  if (!out.s_addr)
    InetPtonA(AF_INET, "127.0.0.1", &out);
  return out;
}
void xn_address(uint8_t *p) {
  std::memset(p, 0, 36);
  auto ip = local_address();
  std::memcpy(p, &ip, 4);
  write16(p + 8, uint16_t(game_port.load()));
  uint64_t id = XboxNativeUserId(0);
  for (unsigned i = 0; i < 6; ++i)
    p[10 + i] = uint8_t(id >> (i * 8));
  p[10] = (p[10] | 2) & 0xFE; // locally administered unicast MAC
}
SOCKET socket_handle(uint32_t handle) {
  auto object =
      rex::system::kernel_state()->object_table()->LookupObject<XSocket>(
          handle);
  if (!object) {
    XThread::SetLastError(WSAENOTSOCK);
    return INVALID_SOCKET;
  }
  return SOCKET(object->native_handle());
}
int send_datagram(uint32_t handle, const uint8_t *data, uint32_t length,
                  int flags, const uint8_t *destination, unsigned size) {
  SOCKET s = socket_handle(handle);
  if (s == INVALID_SOCKET)
    return -1;
  if (!destination || size < 16 || read16(destination) != AF_INET) {
    XThread::SetLastError(WSAEINVAL);
    return -1;
  }
  sockaddr_in to{};
  to.sin_family = AF_INET;
  to.sin_port = htons(read16(destination + 2));
  std::memcpy(&to.sin_addr, destination + 4, 4);
  sockaddr_in chosen{};
  if (REXCVAR_GET(native_direct_ip) && to.sin_addr.s_addr == INADDR_BROADCAST &&
      peer(chosen)) {
    to.sin_addr = chosen.sin_addr;
    if (chosen.sin_port)
      to.sin_port = chosen.sin_port;
  }
  int count = sendto(s, reinterpret_cast<const char *>(data), int(length),
                     flags, reinterpret_cast<sockaddr *>(&to), sizeof(to));
  if (count < 0)
    XThread::SetLastError(WSAGetLastError());
  else
    sent.fetch_add(1);
  return count;
}
class LocalAssignment final : public DeviceAssignment {
  std::vector<DeviceInfo> devices_;

public:
  void OnDevicesChanged(const std::vector<DeviceInfo> &d) override {
    devices_ = d;
  }
  void DevicesForUser(uint32_t user,
                      std::vector<DeviceId> &out) const override {
    out.clear();
    if (user >= XboxNativeLocalPlayers())
      return;
    for (const auto &d : devices_) {
      unsigned assigned = 0;
      auto id = uint64_t(d.id);
      if (d.synthetic && id >= kPadBase && id < kPadBase + 4)
        assigned = unsigned(id - kPadBase);
      else if (!d.synthetic)
        assigned = d.ordinal + ((XboxNativeLocalPlayers() > 1 &&
                                 REXCVAR_GET(native_keyboard_player_one))
                                    ? 1u
                                    : 0u);
      if (assigned == user)
        out.push_back(d.id);
    }
  }
};
class JoinDriver final : public InputDriver {
public:
  JoinDriver() : InputDriver(nullptr, 0) {}
  X_STATUS Setup() override { return X_STATUS_SUCCESS; }
  void EnumerateDevices(std::vector<DeviceInfo> &out) override {
    for (unsigned i = 1; i < XboxNativeLocalPlayers(); ++i)
      if (virtual_pads.load() & (1u << i)) {
        DeviceInfo d;
        d.id = DeviceId(kPadBase + i);
        d.synthetic = true;
        d.name = "Local join shortcut";
        out.push_back(d);
      }
  }
  X_RESULT GetDeviceCapabilities(DeviceId, uint32_t,
                                 X_INPUT_CAPABILITIES *caps) override {
    if (caps) {
      *caps = {};
      caps->type = caps->sub_type = 1;
      caps->gamepad.buttons = 0xFFFF;
    }
    return X_ERROR_SUCCESS;
  }
  X_RESULT GetDeviceState(DeviceId id, X_INPUT_STATE *state) override {
    if (state) {
      *state = {};
      auto index = unsigned(uint64_t(id) - kPadBase);
      state->packet_number = uint32_t(now_ms());
      if (index < 4 &&
          (join_requested.fetch_and(~(1u << index)) & (1u << index)))
        join_until[index].store(now_ms() + 150);
      if (index < 4 && now_ms() < join_until[index].load())
        state->gamepad.buttons = X_INPUT_GAMEPAD_START;
    }
    return X_ERROR_SUCCESS;
  }
  X_RESULT SetDeviceVibration(DeviceId, X_INPUT_VIBRATION *) override {
    return X_ERROR_SUCCESS;
  }
  X_RESULT GetDeviceKeystroke(DeviceId, uint32_t,
                              X_INPUT_KEYSTROKE *) override {
    return X_ERROR_EMPTY;
  }
};
} // namespace
unsigned XboxNativeLocalPlayers() {
  return std::clamp(REXCVAR_GET(native_local_players), 1u, 2u);
}
unsigned long long XboxNativeUserId(unsigned slot) {
  auto text = REXCVAR_GET(native_user_id);
  uint64_t value = 0;
  try {
    value = std::stoull(text, nullptr, 16);
  } catch (...) {
  }
  if (!value)
    value = 0xB13EBABEBABEBABEull;
  return value + slot;
}
std::filesystem::path XboxNativePlayerDirectory(unsigned slot) {
  return slot ? user_root / "local_players" / std::to_string(slot + 1)
              : std::filesystem::path{};
}
void XboxNativeMultiplayerSetup(rex::Runtime *runtime,
                                const std::filesystem::path &root) {
  user_root = root;
  try {
    auto file = root / "campaign-coop.toml";
    if (std::filesystem::exists(file)) {
      auto config = toml::parse_file(file.string());
      if (REXCVAR_GET(native_local_players) == 1)
        rex::cvar::SetFlagByName(
            "native_local_players",
            std::to_string(
                std::clamp(config["local_players"].value_or(1), 1, 2)));
      rex::cvar::SetFlagByName(
          "native_keyboard_player_one",
          config["keyboard_player_one"].value_or(true) ? "true" : "false");
      rex::cvar::SetFlagByName("native_direct_ip",
                               config["direct_ip"].value_or(false) ? "true"
                                                                   : "false");
      if (REXCVAR_GET(native_net_peer).empty())
        rex::cvar::SetFlagByName("native_net_peer",
                                 config["peer"].value_or(std::string{}));
      if (REXCVAR_GET(native_net_address).empty())
        rex::cvar::SetFlagByName("native_net_address",
                                 config["address"].value_or(std::string{}));
    }
  } catch (const std::exception &error) {
    settings_error = error.what();
  }
  auto *input = static_cast<rex::input::InputSystem *>(runtime->input_system());
  input->SetDeviceAssignment(std::make_unique<LocalAssignment>());
  input->AddDriver(std::make_unique<JoinDriver>());
  REXLOG_INFO("[pc-multiplayer] {} local profiles, keyboard-first={}, direct "
              "IP peer={}",
              XboxNativeLocalPlayers(), REXCVAR_GET(native_keyboard_player_one),
              REXCVAR_GET(native_net_peer));
}
void XboxNativeMultiplayerShutdown() { save_settings(); }
void XboxNativeMultiplayerPanel() {
  ImGui::Separator();
  ImGui::TextUnformatted("Campagne coop / ecran partage");
  int count = int(XboxNativeLocalPlayers());
  if (ImGui::SliderInt("Joueurs locaux", &count, 1, 2)) {
    rex::cvar::SetFlagByName("native_local_players", std::to_string(count));
    if (auto *ks = rex::system::kernel_state())
      ks->BroadcastNotification(0xA, (1u << count) - 1);
    save_settings();
  }
  bool keyboard = REXCVAR_GET(native_keyboard_player_one);
  if (ImGui::Checkbox("Clavier J1, premiere manette J2", &keyboard)) {
    rex::cvar::SetFlagByName("native_keyboard_player_one",
                             keyboard ? "true" : "false");
    save_settings();
  }
  for (unsigned i = 1; i < XboxNativeLocalPlayers(); ++i) {
    std::string label = "Start joueur " + std::to_string(i + 1);
    if (ImGui::Button(label.c_str())) {
      virtual_pads.fetch_or(1u << i);
      join_requested.fetch_or(1u << i);
    }
    ImGui::SameLine();
  }
  ImGui::NewLine();
  static char target[64]{};
  static bool initialized = false;
  if (!initialized) {
    auto p = REXCVAR_GET(native_net_peer);
    std::snprintf(target, sizeof(target), "%s", p.c_str());
    initialized = true;
  }
  ImGui::InputText("IP du joueur hote[:port]", target, sizeof(target));
  if (ImGui::Button("Memoriser IP (experimental)")) {
    rex::cvar::SetFlagByName("native_net_peer", target);
    rex::cvar::SetFlagByName("native_direct_ip", "true");
    save_settings();
  }
  ImGui::SameLine();
  if (ImGui::Button("Effacer IP")) {
    target[0] = 0;
    rex::cvar::SetFlagByName("native_net_peer", "");
    rex::cvar::SetFlagByName("native_direct_ip", "true");
    save_settings();
  }
  char ip[INET_ADDRSTRLEN]{};
  auto local = local_address();
  InetNtopA(AF_INET, &local, ip, sizeof(ip));
  ImGui::Text("IP locale %s ; port jeu %u ; UDP envoyes %llu / recus %llu", ip,
              game_port.load(), sent.load(), received.load());
  ImGui::TextWrapped(
      "Local : choisir 2 joueurs puis rejoindre la campagne avec Start sur la "
      "manette. RT suspendu en ecran partage.");
  ImGui::TextDisabled("IP directe : transport experimental ; connexion de "
                      "campagne encore en cours d'integration.");
  if (!settings_error.empty())
    ImGui::TextWrapped("Reglages : %s", settings_error.c_str());
}

REX_HOOK_RAW(__imp__XboxNative_NetDll_sendto) {
  auto to = ctx.r8.u32;
  result(ctx,
         send_datagram(ctx.r4.u32, base + ctx.r5.u32, ctx.r6.u32,
                       int(ctx.r7.u32), to ? base + to : nullptr, ctx.r9.u32));
}
REX_HOOK_RAW(__imp__XboxNative_NetDll_recvfrom) {
  if (ctx.r8.u32 && (!ctx.r9.u32 || read32(base + ctx.r9.u32) < 16)) {
    XThread::SetLastError(WSAEFAULT);
    result(ctx, -1);
    return;
  }
  SOCKET s = socket_handle(ctx.r4.u32);
  if (s == INVALID_SOCKET) {
    result(ctx, -1);
    return;
  }
  sockaddr_in from{};
  int size = sizeof(from);
  int count =
      recvfrom(s, reinterpret_cast<char *>(base + ctx.r5.u32), int(ctx.r6.u32),
               int(ctx.r7.u32), reinterpret_cast<sockaddr *>(&from), &size);
  if (count < 0) {
    XThread::SetLastError(WSAGetLastError());
    result(ctx, -1);
    return;
  }
  if (ctx.r8.u32) {
    auto *p = base + ctx.r8.u32;
    write16(p, AF_INET);
    write16(p + 2, ntohs(from.sin_port));
    std::memcpy(p + 4, &from.sin_addr, 4);
    std::memset(p + 8, 0, 8);
  }
  if (ctx.r9.u32)
    write32(base + ctx.r9.u32, 16);
  received.fetch_add(1);
  result(ctx, count);
}
REX_HOOK_RAW(__imp__XboxNative_NetDll_WSASendTo) {
  if (arg(ctx, base, 9)) {
    XThread::SetLastError(WSAEOPNOTSUPP);
    result(ctx, -1);
    return;
  }
  unsigned buffers = ctx.r6.u32;
  std::vector<uint8_t> bytes;
  if (buffers > 64) {
    XThread::SetLastError(WSAEINVAL);
    result(ctx, -1);
    return;
  }
  for (unsigned i = 0; i < buffers; ++i) {
    auto *entry = base + ctx.r5.u32 + i * 8;
    auto n = read32(entry), address = read32(entry + 4);
    if (n > 65507 || bytes.size() + n > 65507) {
      XThread::SetLastError(WSAEMSGSIZE);
      result(ctx, -1);
      return;
    }
    bytes.insert(bytes.end(), base + address, base + address + n);
  }
  int n = send_datagram(ctx.r4.u32, bytes.data(), unsigned(bytes.size()),
                        int(ctx.r8.u32),
                        ctx.r9.u32 ? base + ctx.r9.u32 : nullptr, ctx.r10.u32);
  if (n >= 0 && ctx.r7.u32)
    write32(base + ctx.r7.u32, uint32_t(n));
  if (n >= 0 && arg(ctx, base, 8))
    rex::system::kernel_state()->CompleteOverlappedImmediateEx(
        arg(ctx, base, 8), 0, 0, n);
  result(ctx, n < 0 ? -1 : 0);
}
REX_HOOK_RAW(__imp__XboxNative_NetDll_XNetGetTitleXnAddr) {
  if (ctx.r4.u32)
    xn_address(base + ctx.r4.u32);
  result(ctx, 4);
}
REX_HOOK_RAW(__imp__XboxNative_NetDll_XNetGetEthernetLinkStatus) {
  result(ctx, 1 | 2 | 8);
}
REX_HOOK_RAW(__imp__XboxNative_NetDll_XNetXnAddrToInAddr) {
  if (!ctx.r4.u32 || !ctx.r6.u32) {
    result(ctx, WSAEINVAL);
    return;
  }
  std::memcpy(base + ctx.r6.u32, base + ctx.r4.u32, 4);
  result(ctx, 0);
}
REX_HOOK_RAW(__imp__XboxNative_NetDll_XNetInAddrToXnAddr) {
  if (!ctx.r5.u32) {
    result(ctx, WSAEINVAL);
    return;
  }
  xn_address(base + ctx.r5.u32);
  write32(base + ctx.r5.u32, ctx.r4.u32);
  result(ctx, 0);
}
REX_HOOK_RAW(__imp__XboxNative_NetDll_XNetInAddrToString) {
  in_addr ip{};
  ip.s_addr = htonl(ctx.r4.u32);
  if (ctx.r5.u32 && ctx.r6.u32)
    InetNtopA(AF_INET, &ip, reinterpret_cast<char *>(base + ctx.r5.u32),
              ctx.r6.u32);
  result(ctx, 0);
}
REX_HOOK_RAW(__imp__XboxNative_NetDll_XNetSetSystemLinkPort) {
  game_port.store(ctx.r4.u32 & 65535);
  result(ctx, 0);
}
REX_HOOK_RAW(__imp__XboxNative_NetDll_XNetGetSystemLinkPort) {
  if (ctx.r4.u32)
    write16(base + ctx.r4.u32, uint16_t(game_port.load()));
  result(ctx, 0);
}
REX_HOOK_RAW(__imp__XboxNative_NetDll_XNetRandom) {
  result(ctx, ctx.r4.u32 && random_bytes(base + ctx.r4.u32, ctx.r5.u32)
                  ? 0
                  : WSAEINVAL);
}
REX_HOOK_RAW(__imp__XboxNative_NetDll_XNetCreateKey) {
  if (!ctx.r4.u32 || !ctx.r5.u32 || !random_bytes(base + ctx.r4.u32, 8) ||
      !random_bytes(base + ctx.r5.u32, 16)) {
    result(ctx, WSAEINVAL);
    return;
  }
  base[ctx.r4.u32] &= 0x1F;
  result(ctx, 0);
}
REX_HOOK_RAW(__imp__XboxNative_NetDll_XNetRegisterKey) {
  if (!ctx.r4.u32 || !ctx.r5.u32) {
    result(ctx, WSAEINVAL);
    return;
  }
  std::lock_guard lock(key_mutex);
  auto &key = keys[std::string(reinterpret_cast<char *>(base + ctx.r4.u32), 8)];
  std::memcpy(key.data(), base + ctx.r5.u32, 16);
  result(ctx, 0);
}
REX_HOOK_RAW(__imp__XboxNative_NetDll_XNetUnregisterKey) {
  std::lock_guard lock(key_mutex);
  if (ctx.r4.u32)
    keys.erase(std::string(reinterpret_cast<char *>(base + ctx.r4.u32), 8));
  result(ctx, 0);
}
REX_HOOK_RAW(__imp__XboxNative_NetDll_XNetUnregisterInAddr) { result(ctx, 0); }

void XboxNativeInstallNetworkRegistry() {
  auto &registry = rex::ppc::GetPPCFuncRegistry();
  // Runtime ordinal imports need the same adapters as the static direct calls.
  std::vector<std::pair<std::string, PPCFunc *>> overrides;
  for (auto [name, function] : registry) {
    std::string n = name;
    constexpr std::string_view prefix = "__imp__XboxNative_";
    if (n.starts_with(prefix))
      overrides.emplace_back("__imp__" + n.substr(prefix.size()), function);
  }
  for (auto &[name, function] : registry)
    for (auto &[target, replacement] : overrides)
      if (target == name)
        function = replacement;
}
