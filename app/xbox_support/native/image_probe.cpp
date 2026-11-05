// Local analysis bridge to the separately built, pinned MIT XenonRecomp backend.
// No guest execution. Output files must not exist.
#include <image.h>
#include <xex.h>
#include <fmt/format.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <vector>

static std::string quote(const std::string& value) {
    std::string result = "\"";
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') result += '\\';
        if (c < 32 || c >= 127) result += fmt::format("\\u{:04x}", c);
        else result += static_cast<char>(c);
    }
    return result + "\"";
}

int main(int argc, char** argv) {
    try {
        if (argc != 4) throw std::runtime_error("Usage: xbox-image-probe input.xex image.bin image.json");
        if (std::filesystem::exists(argv[2]) || std::filesystem::exists(argv[3]))
            throw std::runtime_error("Refusing to overwrite probe output");
        std::ifstream stream(argv[1], std::ios::binary);
        if (!stream) throw std::runtime_error("Cannot read input");
        std::vector<uint8_t> bytes{std::istreambuf_iterator<char>(stream), {}};
        if (bytes.size() < 24 || bytes.size() > 512ull * 1024 * 1024)
            throw std::runtime_error("Invalid input size");
        Image image = Image::ParseImage(bytes.data(), bytes.size());
        if (!image.data || !image.size) throw std::runtime_error("Backend could not load image");
        // The upstream basic-compression loader allocates the block sum, which can
        // be smaller than the security header's page-aligned image size. Never read
        // past that allocation merely to reproduce the declared trailing padding.
        size_t readable = image.size;
        const auto* format = static_cast<const Xex2OptFileFormatInfo*>(getOptHeaderPtr(bytes.data(), XEX_HEADER_FILE_FORMAT_INFO));
        if (format && format->compressionType == XEX_COMPRESSION_BASIC) {
            readable = 0;
            const auto* blocks = reinterpret_cast<const Xex2FileBasicCompressionBlock*>(format + 1);
            const size_t count = (format->infoSize.get() - sizeof(*format)) / sizeof(*blocks);
            for (size_t i = 0; i < count; ++i) readable += blocks[i].dataSize.get() + blocks[i].zeroSize.get();
        }
        if (readable > image.size) throw std::runtime_error("Image block sum exceeds declared image size");
        std::ofstream binary(argv[2], std::ios::binary);
        binary.write(reinterpret_cast<const char*>(image.data.get()), readable);
        if (!binary) throw std::runtime_error("Cannot write image");
        std::ofstream json(argv[3]);
        json << fmt::format("{{\n\"schema_version\":1,\"image_base\":{},\"image_size\":{},\"mapped_size\":{},\"entry_point\":{},\n\"sections\":[", image.base, image.size, readable, image.entry_point);
        bool comma = false;
        for (const auto& section : image.sections) {
            if (comma) json << ',';
            comma = true;
            json << fmt::format("{{\"name\":{},\"address\":{},\"size\":{},\"executable\":{}}}",
                                quote(section.name), section.base, section.size,
                                (section.flags & SectionFlags_Code) ? "true" : "false");
        }
        json << "],\n\"symbols\":[";
        comma = false;
        for (const auto& symbol : image.symbols) {
            if (comma) json << ',';
            comma = true;
            json << fmt::format("{{\"name\":{},\"address\":{},\"size\":{}}}", quote(symbol.name), symbol.address, symbol.size);
        }
        json << "]\n}\n";
        if (!json) throw std::runtime_error("Cannot write metadata");
        std::cout << "Image loaded; guest code was not executed.\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
