#pragma once
#include <memory>
#include <string>
#include "kv/slice.h"

namespace kv {

class Status {
 public:
  enum class Code { kOk = 0, kNotFound = 1, kCorruption = 2 };

  Status() noexcept = default;
  ~Status() = default;
  Status(const Status& rhs);
  Status& operator=(const Status& rhs);
  Status(Status&& rhs) noexcept = default;
  Status& operator=(Status&& rhs) noexcept = default;

  static Status OK() { return Status(); }
  static Status NotFound(const Slice& msg) { return Status(Code::kNotFound, msg); }
  static Status Corruption(const Slice& msg) { return Status(Code::kCorruption, msg); }

  bool ok() const { return state_ == nullptr; }
  Code code() const { return code_; }
  std::string ToString() const;

 private:
  Status(Code code, const Slice& msg);
  Code code_ = Code::kOk;
  std::unique_ptr<std::string> state_;
};

}  // namespace kv
