// Windows launcher for CyDecompilator.
//
// It does one thing: start the private interpreter next to it on app/desktop.py, with no
// console window. It embeds no Python, no model and no business logic, so rebuilding it
// can never affect data/ and a user who deletes it loses nothing but the double-click.
//
// The working directory is set to the Tool root so the application resolves data/ and
// runtime/ from its own folder rather than from wherever the shortcut was invoked.
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <string>

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR arguments, int) {
    wchar_t path[32768];
    if (!GetModuleFileNameW(nullptr, path, 32768)) {
        MessageBoxW(nullptr, L"CyDecompilator could not determine its own location.",
                    L"CyDecompilator", MB_ICONERROR);
        return 1;
    }
    std::wstring root(path);
    root.resize(root.find_last_of(L"\\/"));
    std::wstring python = root + L"\\runtime\\python\\Scripts\\pythonw.exe";
    if (GetFileAttributesW(python.c_str()) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(nullptr,
                    L"The private runtime of CyDecompilator is missing.\n\n"
                    L"Expected: runtime\\python\\Scripts\\pythonw.exe beside this executable.\n"
                    L"See LISEZ-MOI.md for the installation steps.",
                    L"CyDecompilator", MB_ICONERROR);
        return 1;
    }
    std::wstring command = L"\"" + python + L"\" \"" + root + L"\\app\\desktop.py\" " + arguments;
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION process{};
    if (!CreateProcessW(python.c_str(), command.data(), nullptr, nullptr, FALSE,
                        CREATE_NO_WINDOW, nullptr, root.c_str(), &startup, &process)) {
        MessageBoxW(nullptr,
                    L"CyDecompilator could not start.\n\n"
                    L"The runtime is present but the process could not be created.\n"
                    L"See LISEZ-MOI.md.",
                    L"CyDecompilator", MB_ICONERROR);
        return 1;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}
