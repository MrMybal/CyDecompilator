// Native GUI/CLI launchers and the legacy Scripts/python.exe compatibility proxy.
// Full packages use a relocatable interpreter; development venvs remain supported.
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <string>
#include <cstdio>

static std::wstring quoted(const std::wstring& value) {
    std::wstring result = L"\"";
    size_t slashes = 0;
    for (wchar_t c : value) {
        if (c == L'\\') { ++slashes; continue; }
        result.append(slashes * (c == L'"' ? 2 : 1), L'\\');
        slashes = 0;
        if (c == L'"') result += L'\\';
        result += c;
    }
    result.append(slashes * 2, L'\\');
    return result + L'"';
}

static int start(const std::wstring& arguments) {
    wchar_t path[32768];
    if (!GetModuleFileNameW(nullptr, path, 32768)) {
        MessageBoxW(nullptr, L"CyDecompilator could not determine its own location.",
                    L"CyDecompilator", MB_ICONERROR);
        return 1;
    }
    std::wstring root(path);
    root.resize(root.find_last_of(L"\\/"));
#ifdef CYDEC_PYTHON_PROXY
    root.resize(root.find_last_of(L"\\/")); // Scripts/ -> standalone Python directory
    std::wstring python = root + L"\\python.exe";
#elif defined(CYDEC_CLI)
    const wchar_t* executable = L"python.exe";
    std::wstring python = root + L"\\runtime\\python\\" + executable;
    if (GetFileAttributesW(python.c_str()) == INVALID_FILE_ATTRIBUTES)
        python = root + L"\\runtime\\python\\Scripts\\" + executable;
#else
    const wchar_t* executable = L"pythonw.exe";
    std::wstring python = root + L"\\runtime\\python\\" + executable;
    if (GetFileAttributesW(python.c_str()) == INVALID_FILE_ATTRIBUTES)
        python = root + L"\\runtime\\python\\Scripts\\" + executable;
#endif
    if (GetFileAttributesW(python.c_str()) == INVALID_FILE_ATTRIBUTES) {
#if defined(CYDEC_CLI) || defined(CYDEC_PYTHON_PROXY)
        fputws(L"CyDecompilator: private Python runtime is missing. Extract the complete portable package or reinstall.\n", stderr);
#else
        MessageBoxW(nullptr,
                    L"The private runtime of CyDecompilator is missing.\n\n"
                    L"Extract the complete portable package or reinstall CyDecompilator.\n"
                    L"Keep runtime\\ beside this executable. See README.md.",
                    L"CyDecompilator", MB_ICONERROR);
#endif
        return 1;
    }
    std::wstring command = quoted(python) + L" -E -s ";
#ifdef CYDEC_CLI
    command += quoted(root + L"\\app\\tool.py") + L" ";
#elif !defined(CYDEC_PYTHON_PROXY)
    command += quoted(root + L"\\app\\desktop.py") + L" ";
#endif
    command += arguments;
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    DWORD flags = CREATE_NO_WINDOW;
    BOOL inherit = FALSE;
#if defined(CYDEC_CLI) || defined(CYDEC_PYTHON_PROXY)
    flags = 0;
    inherit = TRUE;
    startup.dwFlags = STARTF_USESTDHANDLES;
    startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    startup.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    startup.hStdError = GetStdHandle(STD_ERROR_HANDLE);
#endif
    PROCESS_INFORMATION process{};
    if (!CreateProcessW(python.c_str(), command.data(), nullptr, nullptr, inherit,
                        flags, nullptr,
#ifdef CYDEC_PYTHON_PROXY
                        nullptr,
#else
                        root.c_str(),
#endif
                        &startup, &process)) {
#if defined(CYDEC_CLI) || defined(CYDEC_PYTHON_PROXY)
        fputws(L"CyDecompilator: could not start the private runtime.\n", stderr);
#else
        MessageBoxW(nullptr,
                    L"CyDecompilator could not start.\n\n"
                    L"The runtime is present but the process could not be created.\n"
                    L"See README.md.",
                    L"CyDecompilator", MB_ICONERROR);
#endif
        return 1;
    }
    CloseHandle(process.hThread);
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD result = 1;
    GetExitCodeProcess(process.hProcess, &result);
    CloseHandle(process.hProcess);
    return static_cast<int>(result);
}

#if defined(CYDEC_CLI) || defined(CYDEC_PYTHON_PROXY)
int wmain(int argc, wchar_t** argv) {
    std::wstring arguments;
    for (int i = 1; i < argc; ++i) arguments += quoted(argv[i]) + L" ";
    return start(arguments);
}
#else
int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR arguments, int) { return start(arguments); }
#endif
