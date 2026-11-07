#pragma once
#include <functional>
#include "kv/slice.h"
#include "kv/status.h"

namespace kv {

class Iterator {
 public:
  Iterator();
  Iterator(const Iterator&) = delete;
  Iterator& operator=(const Iterator&) = delete;
  virtual ~Iterator();

  virtual bool Valid() const = 0;
  virtual void Seek(const Slice& target) = 0;
  virtual void Next() = 0;
  virtual Slice key() const = 0;
  virtual Slice value() const = 0;
  virtual Status status() const = 0;

  using CleanupFunction = void (*)(void* arg1, void* arg2);
  void RegisterCleanup(CleanupFunction function, void* arg1, void* arg2);
  void OnDestroy(std::function<void()> fn);

 private:
  struct CleanupNode {
    CleanupFunction function;
    void* arg1;
    void* arg2;
    CleanupNode* next;
  };
  CleanupNode cleanup_head_;
  std::function<void()> on_destroy_;
};

Iterator* NewEmptyIterator();
Iterator* NewErrorIterator(const Status& status);

}  // namespace kv
