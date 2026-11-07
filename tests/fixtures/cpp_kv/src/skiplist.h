#pragma once
#include <atomic>
#include "src/arena.h"

namespace kv {

template <typename Key, class Comparator>
class SkipList {
 private:
  struct Node;

 public:
  explicit SkipList(Comparator cmp, Arena* arena);
  SkipList(const SkipList&) = delete;
  SkipList& operator=(const SkipList&) = delete;

  void Insert(const Key& key);
  bool Contains(const Key& key) const;

  class Iterator {
   public:
    explicit Iterator(const SkipList* list) : list_(list), node_(nullptr) {}
    bool Valid() const { return node_ != nullptr; }
    const Key& key() const { return node_->key; }
    void Next() { node_ = node_->Next(0); }
   private:
    const SkipList* list_;
    Node* node_;
  };

 private:
  Node* NewNode(const Key& key, int height);
  Comparator const compare_;
  Arena* const arena_;
  Node* const head_;
  std::atomic<int> max_height_;
};

template <typename Key, class Comparator>
struct SkipList<Key, Comparator>::Node {
  explicit Node(const Key& k) : key(k) {}
  Key const key;
  Node* Next(int n) { return next_[n].load(std::memory_order_acquire); }
 private:
  std::atomic<Node*> next_[1];
};

template <typename Key, class Comparator>
SkipList<Key, Comparator>::SkipList(Comparator cmp, Arena* arena)
    : compare_(cmp), arena_(arena), head_(NewNode(Key(), 12)), max_height_(1) {}

template <typename Key, class Comparator>
typename SkipList<Key, Comparator>::Node* SkipList<Key, Comparator>::NewNode(const Key& key, int height) {
  char* mem = arena_->Allocate(sizeof(Node) + sizeof(std::atomic<Node*>) * (height - 1));
  return new (mem) Node(key);
}

template <typename Key, class Comparator>
void SkipList<Key, Comparator>::Insert(const Key& key) { (void)NewNode(key, 1); }

template <typename Key, class Comparator>
bool SkipList<Key, Comparator>::Contains(const Key& key) const { return head_ != nullptr && compare_(key, key) == 0; }

}  // namespace kv
