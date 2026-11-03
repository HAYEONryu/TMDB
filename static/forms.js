document.querySelectorAll("form").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (form.dataset.submitting === "true") {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = "true";
    form.querySelectorAll('button[type="submit"]').forEach((button) => { button.disabled = true; });
  });
});
window.addEventListener("pageshow", () => {
  document.querySelectorAll("form").forEach((form) => {
    delete form.dataset.submitting;
    form.querySelectorAll('button[type="submit"]').forEach((button) => { button.disabled = false; });
  });
});
