import "@testing-library/jest-dom";

// jsdom doesn't implement scrollIntoView (real browsers always have it) —
// without this, any component that calls it (e.g. Chat's auto-scroll)
// throws in tests.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
