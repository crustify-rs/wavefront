#pragma once

namespace geometry {

struct Point {
    double x;
    double y;
};

class Rectangle {
public:
    Rectangle(Point lower, Point upper);
    ~Rectangle();

    double area() const;
    double area(double scale) const;

private:
    Point lower_;
    Point upper_;
};

double calculate_area(Point lower, Point upper, double scale);

} // namespace geometry
