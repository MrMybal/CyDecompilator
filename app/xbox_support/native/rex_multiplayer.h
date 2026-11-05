#pragma once
#include <filesystem>
namespace rex {
class Runtime;
}
void XboxNativeMultiplayerSetup(rex::Runtime *, const std::filesystem::path &);
void XboxNativeMultiplayerShutdown();
void XboxNativeMultiplayerPanel();
unsigned XboxNativeLocalPlayers();
unsigned long long XboxNativeUserId(unsigned);
std::filesystem::path XboxNativePlayerDirectory(unsigned);
void XboxNativeInstallNetworkRegistry();
