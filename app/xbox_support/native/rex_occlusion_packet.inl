// EVENT_WRITE_ZPD snapshots a running hardware counter. Both ordinary D3D
// queries and QueryBatch subtract snapshots; the sentinel is a completion
// marker, not a reliable BEGIN/END discriminator for QueryBatch.
bool D3D12CommandProcessor::ExecutePacketType3_EVENT_WRITE_ZPD(
    memory::RingBuffer *reader, uint32_t packet, uint32_t count) {
  if (!REXCVAR_GET(occlusion_query_enable) ||
      !occlusion_query_resources_available_)
    return CommandProcessor::ExecutePacketType3_EVENT_WRITE_ZPD(reader, packet,
                                                                count);
  assert_true(count == 1);
  WriteRegister(XE_GPU_REG_VGT_EVENT_INITIATOR,
                reader->ReadAndSwap<uint32_t>() & 0x3F);
  uint32_t address = register_file_->values[XE_GPU_REG_RB_SAMPLE_COUNT_ADDR];
  auto *result =
      memory_->TranslatePhysical<xenos::xe_gpu_depth_sample_counts *>(address);
  if (!result)
    return true;
  // Compatibility fallback for Saber QueryBatch. This is deliberately opt-in:
  // it supplies bounded survey counters, not physical lens-flare visibility.
  int range = REXCVAR_GET(native_querybatch_range);
  if (range > 0) {
    uint32_t limit = uint32_t(std::min(range, 65536));
    occlusion_snapshot_counter_ %= limit;
    WriteGuestOcclusionResult(result, occlusion_snapshot_counter_++);
    return true;
  }
  if (active_occlusion_query_.valid) {
    xenos::xe_gpu_depth_sample_counts interval{};
    bool completed = EndGuestOcclusionQuery(address, &interval);
    if (!completed && device_removed_)
      return false;
    // Hardware counters wrap at 32 bits; preserve the guest's subtraction.
    if (completed)
      occlusion_snapshot_counter_ += interval.ZPass_A + interval.ZPass_B;
  }
  WriteGuestOcclusionResult(result, occlusion_snapshot_counter_);
  bool began = BeginGuestOcclusionQuery(address);
  return began || !device_removed_;
}
