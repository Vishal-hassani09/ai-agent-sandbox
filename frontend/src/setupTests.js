import '@testing-library/jest-dom';

// JSDOM does not provide scrollIntoView
window.HTMLElement.prototype.scrollIntoView = () => {};