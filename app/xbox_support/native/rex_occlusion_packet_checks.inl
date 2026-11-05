// Compile the actual packet handler against simulated memory and host-query
// completion. Covers conventional pairs, unpaired QueryBatch snapshots and wrap.
#include <bit>
#include <algorithm>
#include <cstdint>
#include <stdexcept>
namespace occlusion_packet_check {
namespace rex {
inline uint32_t byte_swap(uint32_t x) { return std::byteswap(x); }
} // namespace rex
namespace memory {
struct RingBuffer {
  template <class T> T ReadAndSwap() { return T(0); }
};
} // namespace memory
namespace xenos {
struct xe_gpu_depth_sample_counts {
  uint32_t Total_A, Total_B, ZFail_A, ZFail_B, ZPass_A, ZPass_B, StencilFail_A,
      StencilFail_B;
};
} // namespace xenos
constexpr unsigned XE_GPU_REG_VGT_EVENT_INITIATOR = 0,
                   XE_GPU_REG_RB_SAMPLE_COUNT_ADDR = 1;
struct GuestMemory {
  xenos::xe_gpu_depth_sample_counts records[8]{};
  template <class T> T TranslatePhysical(uint32_t address) {
    return address >= 0x1000 && address < 0x1100
               ? reinterpret_cast<T>(&records[(address - 0x1000) / 32])
               : nullptr;
  }
};
struct CommandProcessor {
  bool ExecutePacketType3_EVENT_WRITE_ZPD(memory::RingBuffer *, uint32_t,
                                          uint32_t) {
    return true;
  }
};
struct D3D12CommandProcessor : CommandProcessor {
  GuestMemory memory;
  GuestMemory *memory_ = &memory;
  struct {
    uint32_t values[2]{};
  } registers;
  decltype(registers) *register_file_ = &registers;
  bool device_removed_ = false, occlusion_query_resources_available_ = true;
  struct {
    uint32_t sample_count_address = 0;
    bool valid = false;
  } active_occlusion_query_;
  uint32_t samples = 23, begins = 0, ends = 0;
  uint32_t occlusion_snapshot_counter_ = 0;
  int native_querybatch_range = 0;
  bool occlusion_query_enable = true;
  void WriteRegister(unsigned r, uint32_t value) {
    registers.values[r] = value;
  }
  void WriteGuestOcclusionResult(xenos::xe_gpu_depth_sample_counts *result,
                                 uint64_t value) {
    *result = {};
    result->Total_A = result->ZPass_A = uint32_t(value);
  }
  bool BeginGuestOcclusionQuery(uint32_t address) {
    ++begins;
    active_occlusion_query_ = {address, true};
    return true;
  }
  bool EndGuestOcclusionQuery(uint32_t,
                              xenos::xe_gpu_depth_sample_counts *result) {
    ++ends;
    active_occlusion_query_ = {};
    WriteGuestOcclusionResult(result, samples);
    return true;
  }
  bool ExecutePacketType3_EVENT_WRITE_ZPD(memory::RingBuffer *, uint32_t,
                                          uint32_t);
};
#pragma push_macro("REXCVAR_GET")
#pragma push_macro("REXGPU_WARN")
#pragma push_macro("assert_true")
#undef REXCVAR_GET
#undef REXGPU_WARN
#undef assert_true
#define REXCVAR_GET(name) name
#define REXGPU_WARN(...) ((void)0)
#define assert_true(value)                                                     \
  do {                                                                         \
    if (!(value))                                                              \
      throw std::runtime_error("Occlusion packet invariant failed");           \
  } while (0)
#include "rex_occlusion_packet.inl"
#pragma pop_macro("assert_true")
#pragma pop_macro("REXGPU_WARN")
#pragma pop_macro("REXCVAR_GET")
inline void Run() {
  D3D12CommandProcessor gpu;
  memory::RingBuffer ring;
  auto send = [&](unsigned record, bool end) {
    gpu.registers.values[1] = 0x1000 + record * 32;
    if (end)
      gpu.memory.records[record].ZPass_A = rex::byte_swap(0xFFFFFEEDu);
    if (!gpu.ExecutePacketType3_EVENT_WRITE_ZPD(&ring, 0, 1))
      throw std::runtime_error("Occlusion packet failed");
  };
  send(0, true); // orphan end during a menu transition
  if (!gpu.occlusion_query_resources_available_ ||
      gpu.memory.records[0].ZPass_A != 0)
    throw std::runtime_error(
        "Orphan end disabled queries or fabricated visibility");
  send(2, false);
  send(3, true); // valid adjacent snapshots after the orphan
  if (gpu.begins != 3 || gpu.ends != 2 ||
      gpu.memory.records[3].ZPass_A - gpu.memory.records[2].ZPass_A != 23)
    throw std::runtime_error(
        "Host visibility did not recover after orphan end");
  gpu.samples = 0;
  send(4, false);
  send(5, true);
  if (gpu.memory.records[5].ZPass_A - gpu.memory.records[4].ZPass_A != 0)
    throw std::runtime_error("Occluded flare received a nonzero counter");
  gpu.samples = 41;
  send(1, true); // QueryBatch can jump between nonadjacent marked slots.
  send(7, true);
  if (gpu.memory.records[7].ZPass_A - gpu.memory.records[1].ZPass_A != 41)
    throw std::runtime_error("QueryBatch lost its running counter");
  gpu.occlusion_snapshot_counter_ = 0xFFFFFFF0u;
  gpu.samples = 32;
  send(6, false);
  if (gpu.memory.records[6].ZPass_A != 16)
    throw std::runtime_error("Snapshot counter did not wrap like Xenos");
  D3D12CommandProcessor batch;
  batch.native_querybatch_range = 256;
  for (uint32_t i = 0; i < 258; ++i) {
    batch.registers.values[1] = 0x1000;
    batch.ExecutePacketType3_EVENT_WRITE_ZPD(&ring, 0, 1);
    if (batch.memory.records[0].ZPass_A != (i & 255) || batch.begins)
      throw std::runtime_error("Bounded QueryBatch compatibility failed");
  }
}
} // namespace occlusion_packet_check
