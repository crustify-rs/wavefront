#pragma once
#include <atomic>
#include <cstddef>
#include <vector>

namespace kv {

class Arena {
 public:
  Arena();
  Arena(const Arena&) = delete;
  Arena& operator=(const Arena&) = delete;
  ~Arena();

  char* Allocate(std::size_t bytes);
  std::size_t MemoryUsage() const { return memory_usage_.load(std::memory_order_relaxed); }

 private:
  char* AllocateNewBlock(std::size_t block_bytes);
  char* alloc_ptr_;
  std::size_t alloc_bytes_remaining_;
  std::vector<char*> blocks_;
  std::atomic<std::size_t> memory_usage_;
};

}  // namespace kv
