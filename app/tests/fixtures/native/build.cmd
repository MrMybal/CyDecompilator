@echo off
setlocal
for /f "usebackq tokens=*" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -property installationPath`) do set VS=%%i
call "%VS%\VC\Auxiliary\Build\vcvars64.bat" >nul
cl /nologo /MD /LD /Od /Zi funcs.c /Fefuncs_x64_od.dll /Fdfuncs_x64_od.pdb /link /DEBUG /INCREMENTAL:NO >nul || exit /b 1
cl /nologo /MD /LD /O2 /Zi funcs.c /Fefuncs_x64_o2.dll /Fdfuncs_x64_o2.pdb /link /DEBUG /INCREMENTAL:NO >nul || exit /b 1
call "%VS%\VC\Auxiliary\Build\vcvars32.bat" >nul
cl /nologo /MD /LD /Od /Zi funcs.c /Fefuncs_x86_od.dll /Fdfuncs_x86_od.pdb /link /DEBUG /INCREMENTAL:NO >nul || exit /b 1
cl /nologo /MD /LD /O2 /Zi funcs.c /Fefuncs_x86_o2.dll /Fdfuncs_x86_o2.pdb /link /DEBUG /INCREMENTAL:NO >nul || exit /b 1
del *.obj *.exp *.ilk vc*.pdb 2>nul
