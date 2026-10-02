@echo off
rem ARM64 fixtures with the clang/lld that ship with Visual Studio (no ARM64 MSVC needed):
rem Windows PE DLLs and Linux ELF shared objects, -O0 and -O2.
setlocal
cd /d "%~dp0"
for /f "usebackq tokens=*" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -property installationPath`) do set VS=%%i
set L=%VS%\VC\Tools\Llvm\x64\bin
for %%o in (O0 O2) do (
  "%L%\clang.exe" --target=aarch64-pc-windows-msvc -%%o -fno-stack-protector -c funcs.c -o pe_%%o.obj || exit /b 1
  "%L%\lld-link.exe" /dll /noentry /machine:arm64 /nodefaultlib pe_%%o.obj /out:funcs_arm64_%%o.dll >nul || exit /b 1
  "%L%\clang.exe" --target=aarch64-linux-gnu -%%o -fPIC -fno-stack-protector -nostdlib -shared -fuse-ld=lld funcs.c -o funcs_arm64_%%o.so || exit /b 1
)
del pe_*.obj funcs_arm64_*.lib funcs_arm64_*.exp 2>nul
