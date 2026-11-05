#pragma once
#include <cstdint>
#include <filesystem>
#include <memory>
namespace rex {
class Runtime;
namespace ui {
class Window;
class ImGuiDrawer;
} // namespace ui
} // namespace rex
class NativeControls {
public:
  NativeControls(rex::Runtime *, rex::ui::Window *, rex::ui::ImGuiDrawer *,
                 const std::filesystem::path &);
  ~NativeControls();
  void ProbeButtons(uint16_t buttons);
  void ProbeAntialiasing(int mode);
  void ProbeMove(int16_t x, int16_t y);
  void ProbeKey(uint32_t scancode, bool down);

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};
