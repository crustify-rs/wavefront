#include "geometry.hpp"

namespace geometry {

Rectangle::Rectangle(Point lower, Point upper) : lower_(lower), upper_(upper) {}

Rectangle::~Rectangle() {}

double Rectangle::area() const {
    return (upper_.x - lower_.x) * (upper_.y - lower_.y);
}

double Rectangle::area(double scale) const {
    return area() * scale * scale;
}

double calculate_area(Point lower, Point upper, double scale) {
    Rectangle rectangle(lower, upper);
    return rectangle.area(scale);
} // The destructor runs at scope exit.

} // namespace geometry
