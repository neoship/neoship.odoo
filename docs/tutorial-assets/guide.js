"use strict";

const dialog = document.querySelector("#lightbox");
if (dialog && typeof dialog.showModal === "function") {
  const preview = dialog.querySelector("img");
  const viewport = document.createElement("div");
  viewport.className = "lightbox-image";
  viewport.tabIndex = 0;
  viewport.setAttribute("role", "region");
  const slovak = document.documentElement.lang === "sk";
  viewport.setAttribute("aria-label", slovak ? "Zväčšený obrázok; posúvajte vodorovne aj zvisle" : "Enlarged screenshot; scroll horizontally and vertically");
  preview.replaceWith(viewport);
  const hint = document.createElement("p");
  hint.className = "lightbox-hint";
  hint.textContent = slovak ? "Obrázok môžete posúvať; Escape ho zavrie." : "Scroll the image to explore; Escape closes it.";
  viewport.insertAdjacentElement("afterend", hint);
  const caption = dialog.querySelector("p");
  const close = dialog.querySelector("button");
  for (const button of document.querySelectorAll(".shot")) {
    function openScreenshot() {
      const image = button.querySelector("img");
      const stage = button.querySelector(".screenshot-stage");
      viewport.replaceChildren((stage || image).cloneNode(true));
      const figureCaption = button.closest("figure").querySelector("figcaption").cloneNode(true);
      const figureNumber = figureCaption.querySelector(".fig-no");
      const prefix = figureNumber ? `${figureNumber.textContent} · ` : "";
      if (figureNumber) figureNumber.remove();
      caption.textContent = prefix + figureCaption.textContent.trim();
      dialog.showModal();
      viewport.scrollTo(0, 0);
      close.focus();
    }
    button.addEventListener("click", openScreenshot);
  }
  close.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
}

for (const button of document.querySelectorAll("[data-print]")) {
  button.addEventListener("click", () => window.print());
}

const links = [...document.querySelectorAll(".rail nav a")];
const sections = [...document.querySelectorAll("main section[id]")];
const progress = document.querySelector(".progress");
let queued = false;
function updatePosition() {
  queued = false;
  const range = document.documentElement.scrollHeight - window.innerHeight;
  if (progress) progress.style.transform = `scaleX(${range > 0 ? window.scrollY / range : 0})`;
  const current = sections.filter((section) => section.getBoundingClientRect().top < 170).at(-1);
  for (const link of links) {
    if (current && link.hash === `#${current.id}`) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  }
}
window.addEventListener("scroll", () => {
  if (!queued) {
    queued = true;
    window.requestAnimationFrame(updatePosition);
  }
}, { passive: true });
updatePosition();

const filter = document.querySelector("#carrier-filter");
if (filter) {
  const rows = [...document.querySelectorAll("#carrier-matrix tbody tr")];
  const count = document.querySelector("#carrier-count");
  filter.addEventListener("input", () => {
    const query = filter.value.trim().toLocaleLowerCase();
    for (const row of rows) row.hidden = !row.textContent.toLocaleLowerCase().includes(query);
    count.textContent = `${rows.filter((row) => !row.hidden).length} of ${rows.length} carriers shown`;
  });
}
