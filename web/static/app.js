// ChapaShop — интерфейс сайта. Весь текст выводится через textContent — защита от XSS.
// Корзина хранится в браузере (localStorage), а цены и итог всегда пересчитывает сервер.
(() => {
const CART_KEY = "chapashop_cart_v1";
const state = { category: null, q: "", sort: "new", onlyAvail: false, cats: [], shop: {} };
const $ = (s) => document.querySelector(s);
const view = $("#view");

function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "text") e.textContent = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c != null) e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return e;
}
// Telegram Mini App: initData отправляется на сервер, где проверяется подпись.
const TG = window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData ? window.Telegram.WebApp : null;
async function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {});
  if (TG) headers["X-Telegram-Init-Data"] = TG.initData;
  if (opts.body) headers["Content-Type"] = "application/json";
  const r = await fetch(path, Object.assign({}, opts, { headers }));
  if (!r.ok) { let d = ""; try { d = (await r.json()).detail; } catch {} const e = new Error(typeof d === "string" && d ? d : String(r.status)); e.status = r.status; throw e; }
  return r.json();
}
const fmtDate = (s) => new Date(s).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
const PAY_RU = { pending: "Ожидает оплаты", paid: "Оплачен", refunded: "Возврат", failed: "Ошибка оплаты" };
const stars = (n) => (n === 0 ? "Бесплатно" : `${n} ⭐`);
// Цена: итоговая + зачёркнутая старая (если есть скидка).
const priceNode = (p, cls = "price") => h("div", { class: cls }, stars(p.price_stars), p.old_price_stars ? h("s", { text: String(p.old_price_stars) }) : null);
const salePill = (p) => p.old_price_stars ? h("span", { class: "pill sale", text: `−${p.discount_percent || Math.round(100 - p.price_stars * 100 / p.old_price_stars)}%` }) : null;
function toast(t) { const el = $("#toast"); el.textContent = t; el.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove("show"), 1800); }

// ---------- Проверка Roblox-ника: аватар и имя игрока ----------
function robloxField(input) {
  const box = h("div", { class: "rbx", "aria-live": "polite" });
  let t, seq = 0;
  async function check() {
    const v = input.value.trim(), my = ++seq;
    if (!/^[A-Za-z0-9_]{3,20}$/.test(v)) { box.className = "rbx"; box.replaceChildren(); return; }
    box.className = "rbx wait"; box.replaceChildren(h("span", { text: "Ищем игрока…" }));
    try {
      const r = await api("/api/roblox/lookup?username=" + encodeURIComponent(v));
      if (my !== seq) return;
      if (!r.found) { box.className = "rbx bad"; box.replaceChildren(h("span", { text: "Игрок с таким ником не найден в Roblox" })); return; }
      box.className = "rbx ok";
      box.replaceChildren(
        r.avatar_url ? h("img", { src: r.avatar_url, alt: "", width: 44, height: 44 }) : h("div", { class: "ph", text: "👤" }),
        h("div", {}, h("b", { text: r.display_name }), h("small", { text: "@" + r.name + " · ник найден ✓" })));
      input.dataset.canon = r.name;
    } catch { if (my === seq) { box.className = "rbx"; box.replaceChildren(h("small", { text: "Не удалось проверить ник — его всё равно можно использовать" })); } }
  }
  input.addEventListener("input", () => { clearTimeout(t); delete input.dataset.canon; t = setTimeout(check, 500); });
  input.addEventListener("blur", () => { if (input.dataset.canon && input.dataset.canon.toLowerCase() === input.value.trim().toLowerCase()) input.value = input.dataset.canon; });
  if (input.value) check();
  return box;
}

// ---------- Корзина ----------
const cart = {
  read() { try { const v = JSON.parse(localStorage.getItem(CART_KEY) || "[]"); return Array.isArray(v) ? v.filter((x) => Number.isInteger(x.product_id) && Number.isInteger(x.quantity) && x.quantity > 0) : []; } catch { return []; } },
  write(items) { localStorage.setItem(CART_KEY, JSON.stringify(items)); updateBadge(); },
  qty(id) { return (this.read().find((x) => x.product_id === id) || {}).quantity || 0; },
  set(id, q) { const items = this.read().filter((x) => x.product_id !== id); if (q > 0) items.push({ product_id: id, quantity: Math.min(99, q) }); this.write(items); },
  add(id, q = 1) { this.set(id, this.qty(id) + q); },
  count() { return this.read().reduce((s, x) => s + x.quantity, 0); },
};
function updateBadge() {
  const n = cart.count();
  for (const b of [$("#cart-badge"), $("#cart-badge2")]) { b.hidden = !n; b.textContent = n > 99 ? "99+" : n; }
  // Плавающая кнопка «Корзина (N)» над нижним меню — как в популярных Mini App-магазинах.
  let bar = $("#cartbar");
  if (!bar) { bar = h("a", { id: "cartbar", class: "cartbar", href: "/cart", "data-link": true }); document.body.append(bar); }
  const onCart = location.pathname.startsWith("/cart");
  bar.hidden = !n || onCart;
  bar.replaceChildren(h("span", { text: `🛒 Корзина (${n})` }), h("span", { text: "Перейти ›" }));
}

// ---------- Общие элементы ----------
const CAT_STYLE = {
  pets: ["🐾", "#b57bff", "#7b2ff7"], eggs: ["🥚", "#ffb86b", "#ff7a59"],
  potions: ["🧪", "#6ad6ff", "#4d7cff"], other: ["🎁", "#ff8fc7", "#c14bff"],
};
const catSlug = (id) => (state.cats.find((c) => c.id === id) || {}).slug;
function productImage(p, cls = "img") {
  const box = h("div", { class: cls });
  if (p.image_url) { box.append(h("img", { src: p.image_url, alt: p.name, loading: "lazy" })); return box; }
  const [glyph, c1, c2] = CAT_STYLE[catSlug(p.category_id)] || ["★", "#b57bff", "#7b2ff7"];
  box.classList.add("art"); box.style.setProperty("--c1", c1); box.style.setProperty("--c2", c2);
  box.append(h("span", { class: "glyph", "aria-hidden": "true" }, glyph));
  return box;
}
function catName(id) { return (state.cats.find((c) => c.id === id) || {}).name || "Без категории"; }

function card(p) {
  const img = productImage(p);
  if (p.is_demo) img.append(h("span", { class: "pill", text: "Демо" }));
  if (!p.is_available) img.append(h("span", { class: "pill off", text: "Нет в наличии" }));
  const sp = salePill(p); if (sp) img.append(sp);
  const btn = h("button", { class: "btn btn-primary", disabled: !p.is_available, onclick: (e) => {
    e.preventDefault(); e.stopPropagation(); cart.add(p.id); toast("Добавлено в корзину");
    btn.textContent = `В корзине: ${cart.qty(p.id)}`; btn.classList.add("in");
  } }, p.is_available ? (cart.qty(p.id) ? `В корзине: ${cart.qty(p.id)}` : "В корзину") : "Нет в наличии");
  if (p.is_available && cart.qty(p.id)) btn.classList.add("in");
  return h("a", { class: "card", href: `/product/${p.id}`, "data-link": true }, img,
    h("div", { class: "body" },
      h("div", { class: "name", text: p.name }),
      priceNode(p),
      h("div", { class: "tag", text: catName(p.category_id) }),
      btn));
}

// ---------- Страницы ----------
async function pageHome() {
  document.title = "ChapaShop — магазин Adopt Me за Telegram Stars";
  const grid = h("section", { class: "grid", id: "grid" }, ...Array.from({ length: 6 }, () => h("div", { class: "skel" })));
  const count = h("div", { class: "count" });
  const sort = h("select", { "aria-label": "Сортировка", onchange: (e) => { state.sort = e.target.value; loadProducts(); } },
    ...[["new", "Сначала новые"], ["price_asc", "Дешевле"], ["price_desc", "Дороже"], ["name", "По названию"]]
      .map(([v, t]) => h("option", { value: v, selected: state.sort === v }, t)));
  const avail = h("input", { type: "checkbox", checked: state.onlyAvail, onchange: (e) => { state.onlyAvail = e.target.checked; loadProducts(); } });
  const cats = h("nav", { class: "cats", "aria-label": "Категории" });
  const notice = state.shop.payments_enabled ? null : h("div", { class: "notice", text: "Тестовый режим: оплата пока не подключена, все товары — демо." });
  view.replaceChildren(
    h("section", { class: "hero" },
      h("div", {}, h("h1", { text: state.shop.shop_name || "ChapaShop" }),
        h("p", { text: state.shop.shop_description || "Магазин товаров Adopt Me с оплатой в Telegram Stars" })),
      h("div", { class: "hero-cta" },
        h("a", { class: "btn", href: "#grid", onclick: (e) => { e.preventDefault(); $("#grid").scrollIntoView({ behavior: "smooth" }); } }, "Смотреть каталог"),
        h("a", { class: "btn alt", href: "/about", "data-link": true }, "Как это работает")),
      h("div", { class: "hero-art", "aria-hidden": "true" })),
    notice || "", h("h2", { class: "sec-title", text: "Категории" }), cats,
    h("div", { class: "toolbar" }, count, h("div", { class: "ctrls" }, h("label", { class: "chk" }, avail, "В наличии"), sort)),
    grid);

  function renderCats() {
    const mk = (label, slug, icon) => h("button", { class: "cat" + (state.category === slug ? " on" : ""), onclick: () => { state.category = slug; renderCats(); loadProducts(); } }, h("i", { text: icon }), label);
    cats.replaceChildren(mk("Все", null, "✨"), ...state.cats.map((c) => mk(c.name, c.slug, (CAT_STYLE[c.slug] || ["★"])[0])));
  }
  async function loadProducts() {
    const p = new URLSearchParams({ sort: state.sort });
    if (state.q) p.set("q", state.q);
    if (state.category) p.set("category", state.category);
    if (state.onlyAvail) p.set("available", "true");
    try {
      const items = await api("/api/products?" + p);
      count.textContent = `Товаров: ${items.length}`;
      if (!items.length) return grid.replaceChildren(h("div", { class: "empty" }, "Ничего не найдено",
        h("br"), h("button", { class: "btn btn-ghost", onclick: () => { state.q = ""; $("#search").value = ""; state.category = null; state.onlyAvail = false; pageHome(); } }, "Сбросить фильтры")));
      grid.replaceChildren(...items.map(card));
    } catch { grid.replaceChildren(h("div", { class: "empty", text: "Не удалось загрузить каталог. Обновите страницу." })); }
  }
  pageHome.reload = loadProducts;
  renderCats(); loadProducts();
}

async function pageProduct(id) {
  view.replaceChildren(h("div", { class: "skel", style: "aspect-ratio:2;margin:16px 0" }));
  let p;
  try { p = await api(`/api/products/${id}`); } catch {
    return view.replaceChildren(h("div", { class: "empty" }, "Товар не найден", h("br"), h("a", { class: "btn btn-ghost", href: "/", "data-link": true }, "В каталог")));
  }
  document.title = `${p.name} — ChapaShop`;
  let q = Math.max(1, cart.qty(p.id) || 1);
  const qn = h("span", { text: q });
  const minus = h("button", { "aria-label": "Меньше", onclick: () => { q = Math.max(1, q - 1); qn.textContent = q; } }, "−");
  const plus = h("button", { "aria-label": "Больше", onclick: () => { q = Math.min(99, q + 1); qn.textContent = q; } }, "+");
  const img = productImage(p);
  if (p.is_demo) img.append(h("span", { class: "pill", text: "Демо" }));
  const sp2 = salePill(p); if (sp2) img.append(sp2);
  view.replaceChildren(
    h("div", { class: "crumbs" }, h("a", { href: "/", "data-link": true }, "Каталог"), " / ", catName(p.category_id)),
    h("section", { class: "pp" }, img,
      h("div", {},
        h("h1", { text: p.name }),
        priceNode(p),
        h("span", { class: "status " + (p.is_available ? "ok" : "no"), text: p.is_available ? "В наличии" : "Нет в наличии" }),
        h("p", { class: "desc", text: p.description || "Описание появится позже." }),
        h("div", { class: "facts" },
          h("div", {}, h("span", { text: "Категория" }), h("b", { text: catName(p.category_id) })),
          h("div", {}, h("span", { text: "Оплата" }), h("b", { text: "Telegram Stars ⭐" })),
          h("div", {}, h("span", { text: "Выдача" }), h("b", { text: "Приватный сервер Roblox" }))),
        p.is_available ? h("div", { class: "buy-row" }, h("div", { class: "qty" }, minus, qn, plus),
          h("button", { class: "btn btn-primary", onclick: () => { cart.set(p.id, q); toast(`В корзине: ${q} шт.`); } }, "В корзину")) : "",
        h("p", { class: "tag", style: "margin-top:14px", text: "Товар не связан с Roblox Corporation и Uplift Games." }))),
    h("h2", { class: "sec-title", text: "Как получить заказ" }),
    h("div", { class: "how" },
      ...[["Добавьте в корзину", "Укажите количество и свой Roblox username."], ["Оплатите Stars", "Счёт откроется внутри Telegram."], ["Получите ссылку", "Продавец пришлёт ссылку на приватный сервер."]]
        .map(([b, t], i) => h("div", { class: "step" }, h("div", { class: "n", text: i + 1 }), h("div", {}, h("b", { text: b }), t)))));
}

async function pageCart() {
  document.title = "Корзина — ChapaShop";
  const items = cart.read();
  if (!items.length) return view.replaceChildren(h("h2", { class: "title", text: "Корзина" }),
    h("div", { class: "empty" }, "Корзина пуста", h("br"), h("a", { class: "btn btn-primary", href: "/", "data-link": true }, "Перейти в каталог")));
  let quote;
  try { quote = await api("/api/cart/quote", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items, promo_code: state.promo || null }) }); }
  catch { return view.replaceChildren(h("div", { class: "empty", text: "Не удалось пересчитать корзину" })); }
  if (quote.removed.length) { cart.write(items.filter((x) => !quote.removed.includes(x.product_id))); toast("Некоторые товары больше недоступны"); }

  const lines = quote.items.map((l) => {
    const step = (d) => { cart.set(l.product_id, l.quantity + d); pageCart(); };
    return h("div", { class: "line" + (l.available ? "" : " off") },
      productImage({ category_id: l.category_id, image_url: l.image_url, name: l.name }),
      h("div", {},
        h("a", { class: "nm", href: `/product/${l.product_id}`, "data-link": true, text: l.name }),
        h("div", { class: "tag", text: l.available ? `${stars(l.price_stars)} за шт.${l.old_price_stars ? ` (было ${l.old_price_stars})` : ""}` : "Нет в наличии — не войдёт в заказ" }),
        h("div", { class: "row" },
          h("div", { class: "qty" }, h("button", { disabled: l.quantity <= 1, onclick: () => step(-1), "aria-label": "Меньше" }, "−"), h("span", { text: l.quantity }), h("button", { onclick: () => step(1), "aria-label": "Больше" }, "+")),
          h("b", { text: stars(l.subtotal) })),
        h("button", { class: "rm", onclick: () => { cart.set(l.product_id, 0); pageCart(); } }, "Удалить")));
  });

  const err = h("div", { class: "err" });
  const saved = localStorage.getItem("chapashop_roblox") || "";
  const nick = h("input", { type: "text", maxlength: 20, placeholder: "Например, Player_123", value: saved, autocomplete: "off", autocapitalize: "off", spellcheck: "false" });
  if (TG && !saved && state.me && state.me.roblox_username) nick.value = state.me.roblox_username;
  nick.addEventListener("input", () => { try { localStorage.setItem("chapashop_roblox", nick.value.trim()); } catch {} });   // ник не пропадает, когда корзина перерисовывается (промокод, количество)
  const promoErr = h("div", { class: "err", text: quote.promo_error || "" });
  const promoIn = h("input", { type: "text", maxlength: 32, placeholder: "Промокод", value: state.promo || "", autocapitalize: "characters", autocomplete: "off", spellcheck: "false" });
  const promoBtn = h("button", { class: "btn btn-ghost", type: "button", onclick: () => { state.promo = promoIn.value.trim().toUpperCase(); pageCart(); } }, quote.promo_code ? "Изменить" : "Применить");
  const promoOk = quote.promo_code && !quote.promo_error ? h("div", { class: "promo-ok", text: `Применён: ${quote.promo_title ? quote.promo_title + " · " : ""}${quote.promo_code}` }) : "";
  const promoRow = h("div", { class: "field" }, "Промокод (если есть)", h("div", { class: "promo" }, promoIn, promoBtn), promoErr, promoOk);
  promoIn.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); promoBtn.click(); } });
  const checkout = h("a", { class: "btn btn-primary btn-block", href: "#", onclick: async (e) => {
    e.preventDefault();
    const v = nick.value.trim();
    if (!/^[A-Za-z0-9_]{3,20}$/.test(v)) { err.textContent = "3–20 символов: латиница, цифры и _"; return; }
    err.textContent = ""; localStorage.setItem("chapashop_roblox", v);
    if (TG) {
      checkout.setAttribute("aria-disabled", "true");
      try {
        const o = await api("/api/orders", { method: "POST", body: JSON.stringify({ roblox_username: v, items: quote.items.filter((l) => l.available).map((l) => ({ product_id: l.product_id, quantity: l.quantity })), promo_code: quote.promo_code || null }) });
        cart.write([]); state.promo = ""; toast(`Заказ ${o.number} создан`); go(`/orders/${o.id}`);
      } catch (x) { err.textContent = x.message; checkout.removeAttribute("aria-disabled"); }
      return;
    }
    const bot = state.shop.bot_username;
    if (!bot) { toast("Telegram-бот ещё не подключён"); return; }
    window.open(`https://t.me/${encodeURIComponent(bot)}?start=shop`, "_blank", "noopener");
  } }, TG ? "К оформлению  ›" : "Оформить в Telegram  ›");
  view.replaceChildren(h("h2", { class: "title", text: "Корзина" }),
    h("div", { class: "cart" }, h("div", { class: "lines" }, lines),
      h("aside", { class: "summary" },
        h("div", { class: "r" }, h("span", { text: `В корзине ${quote.count} шт.` }), h("span", { text: stars(quote.subtotal_stars) })),
        quote.discount_stars ? h("div", { class: "r disc" }, h("span", { text: `Скидка (${quote.promo_title || quote.promo_code})` }), h("span", { text: "−" + stars(quote.discount_stars) })) : "",
        h("div", { class: "t" }, h("span", { text: "Итого" }), h("span", { text: stars(quote.total_stars) })),
        h("label", { class: "field" }, "Ваш Roblox username", nick, err, robloxField(nick)),
        promoRow,
        checkout,
        h("div", { class: "hint", text: TG ? "После оформления откроется заказ с кнопкой оплаты в Telegram Stars." : "Оплата проходит в Telegram Stars внутри Telegram. Промокод нужно будет ввести ещё раз при оформлении в Telegram. Цены пересчитываются сервером." }),
        h("button", { class: "rm", onclick: () => { cart.write([]); pageCart(); } }, "Очистить корзину"))));
}

function pageAbout() {
  document.title = "О магазине — ChapaShop";
  const s = state.shop;
  view.replaceChildren(h("section", { class: "about" },
    h("h2", { text: s.shop_name || "ChapaShop" }), h("p", { text: s.shop_description || "" }),
    h("h3", { text: "Как проходит заказ" }), h("p", { text: "Выберите товары, укажите Roblox username и оплатите в Telegram Stars. После оплаты продавец пришлёт ссылку на приватный сервер и выдаст заказ." }),
    h("h3", { text: "Правила" }), h("p", { text: s.order_rules || "" }),
    h("h3", { text: "Контакты" }), h("p", { text: s.contact_info || "" }),
    h("p", { class: "tag", text: "ChapaShop не связан с Roblox Corporation и Uplift Games." })));
}

function needTG() {
  view.replaceChildren(h("div", { class: "empty" }, "Этот раздел доступен в Telegram Mini App.", h("br"),
    state.shop.bot_username ? h("a", { class: "btn btn-primary", href: `https://t.me/${state.shop.bot_username}`, target: "_blank", rel: "noopener" }, "Открыть в Telegram") : ""));
}
function statusChip(o) {
  const cls = o.status === "delivered" ? "ok" : o.status === "rejected" || o.status === "refunded" ? "no" : "wait";
  return h("span", { class: "status " + cls, text: o.status_ru });
}
async function pageOrders() {
  document.title = "Мои заказы — ChapaShop";
  if (!TG) return needTG();
  view.replaceChildren(h("h2", { class: "title", text: "Мои заказы" }), h("div", { class: "skel" }));
  let list;
  try { list = await api("/api/orders"); } catch (x) { return view.replaceChildren(h("div", { class: "empty", text: x.message })); }
  if (!list.length) return view.replaceChildren(h("h2", { class: "title", text: "Мои заказы" }),
    h("div", { class: "empty" }, "Заказов пока нет", h("br"), h("a", { class: "btn btn-primary", href: "/", "data-link": true }, "В каталог")));
  view.replaceChildren(h("h2", { class: "title", text: "Мои заказы" }), h("div", { class: "orders" },
    list.map((o) => h("a", { class: "order-row", href: `/orders/${o.id}`, "data-link": true },
      h("div", { class: "onum", text: o.number }),
      h("div", { class: "omid" }, h("div", { class: "oname", text: o.items.map((i) => `${i.name} ×${i.quantity}`).join(", ") }),
        h("div", { class: "tag", text: fmtDate(o.created_at) })),
      h("div", { class: "oend" }, h("b", { text: stars(o.total_stars) }), statusChip(o))))));
}
async function pageOrder(id) {
  if (!TG) return needTG();
  view.replaceChildren(h("div", { class: "skel" }));
  let o;
  try { o = await api(`/api/orders/${id}`); } catch { return view.replaceChildren(h("div", { class: "empty", text: "Заказ не найден" })); }
  document.title = `Заказ ${o.number} — ChapaShop`;
  const pdfBtn = h("button", { class: "btn btn-ghost", onclick: (e) => downloadReceipt(o, e.currentTarget) }, "Скачать PDF");
  const sendBtn = h("button", { class: "btn btn-ghost", onclick: async (e) => {
    const b = e.currentTarget; b.setAttribute("aria-disabled", "true");
    try { const r = await api(`/api/orders/${o.id}/receipt`, { method: "POST" }); toast(r.sent ? "Чек отправлен в чат с ботом" : "Не удалось отправить чек, попробуйте позже"); }
    catch (x) { toast(x.message); } finally { b.removeAttribute("aria-disabled"); }
  } }, "Чек в Telegram");
  const unpaid = o.payment_status === "pending" && o.status === "awaiting_payment";
  view.replaceChildren(
    h("div", { class: "crumbs" }, h("a", { href: "/orders", "data-link": true }, "Мои заказы"), " / ", o.number),
    h("section", { class: "order-card" },
      h("div", { class: "order-head" }, h("div", { class: "order-title" }, "Заказ № ", h("span", { class: "big-num", text: o.number })), statusChip(o)),
      h("div", { class: "r" }, h("span", { text: "Дата" }), h("span", { text: fmtDate(o.created_at) })),
      h("div", { class: "r" }, h("span", { text: "Roblox" }), h("span", { text: o.roblox_username })),
      h("div", { class: "r" }, h("span", { text: "Оплата" }), h("span", { text: PAY_RU[o.payment_status] || o.payment_status })),
      h("table", { class: "otable" },
        h("thead", {}, h("tr", {}, h("th", { text: "Наименование" }), h("th", { class: "n", text: "Цена" }), h("th", { class: "n", text: "Кол." }), h("th", { class: "n", text: "Сумма" }))),
        h("tbody", {}, o.items.map((i) => h("tr", {}, h("td", { text: i.name }), h("td", { class: "n", text: stars(i.price_stars) }), h("td", { class: "n", text: String(i.quantity) }), h("td", { class: "n", text: stars(i.subtotal) }))))),
      o.discount_stars ? h("div", { class: "r" }, h("span", { text: `Скидка (${o.promo_code})` }), h("span", { text: "−" + stars(o.discount_stars) })) : "",
      h("div", { class: "t" }, h("span", { text: unpaid ? "К оплате" : "Итого" }), h("span", { text: stars(o.total_stars) })),
      unpaid ? payBlock(o) : "",
      o.server_link ? h("a", { class: "btn btn-primary btn-block", href: o.server_link, target: "_blank", rel: "noopener" }, "Зайти на сервер") : "",
      o.has_receipt ? h("div", { class: "btn-row" }, pdfBtn, sendBtn) : h("div", { class: "hint", text: "PDF-чек появится после оплаты." }),
      h("h3", { text: "История статусов" }),
      h("ol", { class: "timeline" }, o.history.map((x) => h("li", {}, h("b", { text: x.status_ru }), " · ", fmtDate(x.at), x.comment ? h("div", { class: "hint", text: "Причина: " + x.comment }) : "")))));
}
// PDF-чек: сервер выдаёт временную ссылку (10 минут), в Telegram она открывается во внешнем браузере и скачивается.
async function downloadReceipt(o, btn) {
  btn.setAttribute("aria-disabled", "true");
  try {
    const { url } = await api(`/api/orders/${o.id}/receipt-link`, { method: "POST" });
    const full = location.origin + url;
    if (TG && TG.openLink) TG.openLink(full); else location.href = full;
  } catch (x) { toast(x.message); } finally { btn.removeAttribute("aria-disabled"); }
}
function payBlock(o) {
  const err = h("div", { class: "err" });
  if (!state.shop.payments_enabled) return h("div", { class: "notice", text: "Тестовый режим: оплата Telegram Stars не подключена. Успешная оплата не имитируется." });
  const btn = h("button", { class: "btn btn-primary btn-block", onclick: async () => {
    btn.setAttribute("aria-disabled", "true"); err.textContent = "";
    try {
      const { invoice_link } = await api(`/api/orders/${o.id}/invoice`, { method: "POST" });
      TG.openInvoice(invoice_link, (status) => {
        btn.removeAttribute("aria-disabled");
        if (status === "paid") { toast("Оплата получена, проверяем…"); setTimeout(() => pageOrder(o.id), 1500); }
        else if (status === "failed") err.textContent = "Оплата не прошла. Попробуйте ещё раз.";
        else if (status === "cancelled") err.textContent = "Оплата отменена.";
      });
    } catch (x) { err.textContent = x.message; btn.removeAttribute("aria-disabled"); }
  } }, `Оплатить ${o.total_stars} ⭐`);
  return h("div", {}, btn, err, h("div", { class: "hint", text: "Заказ станет «Оплачен» только после подтверждения платежа Telegram." }));
}
async function pageProfile() {
  document.title = "Профиль — ChapaShop";
  if (!TG) return needTG();
  let me;
  try { me = await api("/api/me"); state.me = me; } catch (x) { return view.replaceChildren(h("div", { class: "empty", text: x.message })); }
  const err = h("div", { class: "err" });
  const nick = h("input", { type: "text", maxlength: 20, value: me.roblox_username || "", placeholder: "Player_123", autocapitalize: "off", spellcheck: "false" });
  view.replaceChildren(h("h2", { class: "title", text: "Профиль" }), h("section", { class: "order-card" },
    h("div", { class: "r" }, h("span", { text: "Имя" }), h("span", { text: me.first_name || "—" })),
    h("div", { class: "r" }, h("span", { text: "Telegram" }), h("span", { text: me.username ? "@" + me.username : "—" })),
    h("div", { class: "r" }, h("span", { text: "Telegram ID" }), h("span", { text: String(me.telegram_id) })),
    h("div", { class: "r" }, h("span", { text: "Заказов" }), h("span", { text: String(me.orders_count) })),
    h("label", { class: "field" }, "Roblox username", nick, err, robloxField(nick)),
    h("button", { class: "btn btn-primary btn-block", onclick: async () => {
      try { await api("/api/me/roblox", { method: "PUT", body: JSON.stringify({ roblox_username: nick.value.trim() }) }); err.textContent = ""; toast("Сохранено"); }
      catch (x) { err.textContent = x.message; }
    } }, "Сохранить"),
    h("a", { class: "btn btn-ghost btn-block", href: "/orders", "data-link": true }, "Мои заказы")));
}

// ---------- Заявка блогера на промокод (анкета из нескольких шагов) ----------
const PLATFORMS = { tiktok: { name: "TikTok", example: "https://www.tiktok.com/@ваш_ник", hosts: ["tiktok.com", "www.tiktok.com", "m.tiktok.com", "vm.tiktok.com"] },
                    youtube: { name: "YouTube", example: "https://www.youtube.com/@ваш_канал", hosts: ["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"] } };
const GAMES = { murder_mystery: "Murder Mystery", adopt_me: "Adopt Me" };
const LANGS = { ru: "Русский", uk: "Українська", en: "English" };
const REQ_STATUS = { pending: ["На рассмотрении", "wait"], approved: ["Одобрена", "ok"], rejected: ["Отклонена", "no"] };

async function pagePromo() {
  document.title = "Промокод для блогеров — ChapaShop";
  if (!TG) return needTG();
  view.replaceChildren(h("h2", { class: "title", text: "Свой промокод" }), h("div", { class: "skel" }));
  let st;
  try { st = await api("/api/promo-requests/mine"); } catch (x) { return view.replaceChildren(h("div", { class: "empty", text: x.message })); }
  const w = { step: 1, platform: "", url: "", game: "", lang: "", code: "", contact: (TG.initDataUnsafe && TG.initDataUnsafe.user && TG.initDataUnsafe.user.username) ? "@" + TG.initDataUnsafe.user.username : "" };
  const box = h("div", { class: "wz" });
  const fmtDay = (n) => (n % 10 === 1 && n % 100 !== 11 ? "день" : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? "дня" : "дней");

  function statusCard() {
    const l = st.last; if (!l) return "";
    const [label, cls] = REQ_STATUS[l.status] || [l.status, "wait"];
    const kids = [h("div", { class: "wz-row" }, h("b", { class: "mono", text: l.code }), h("span", { class: "status " + cls, text: label }))];
    if (l.status === "approved") {
      kids.push(h("div", { class: "wz-count" }, h("b", { text: String(l.used_count ?? 0) }), h("span", { text: " чел. ввели ваш промокод" })));
      if (l.percent_now) kids.push(h("p", { class: "hint", text: `Скидка сейчас: ${l.percent_now}%. Чем больше людей вводит промокод, тем больше скидка${l.growth_every ? ` (+1% за каждые ${l.growth_every} чел., до ${l.percent_max}%)` : ""}.` }));
    }
    if (l.status === "pending") kids.push(h("p", { class: "hint", text: "Мы рассмотрим заявку и напишем вам в Telegram." }));
    if (l.status === "rejected" && l.admin_comment) kids.push(h("p", { class: "hint", text: "Причина: " + l.admin_comment }));
    if (!st.can_apply) kids.push(h("p", { class: "hint", text: `Новую заявку можно отправить через ${st.days_left} ${fmtDay(st.days_left)} (раз в 7 дней).` }));
    return h("div", { class: "wz-card" }, h("h3", { text: "Ваша заявка" }), ...kids);
  }
  const nav = (back, next, nextLabel = "Дальше", ok = true) => h("div", { class: "wz-nav" },
    back ? h("button", { class: "btn", type: "button", onclick: back }, "Назад") : "",
    h("button", { class: "btn btn-primary", type: "button", disabled: ok ? null : true, onclick: next }, nextLabel));
  const choice = (map, cur, pick) => h("div", { class: "wz-choice" }, Object.entries(map).map(([k, v]) =>
    h("button", { class: "wz-opt" + (cur === k ? " on" : ""), type: "button", onclick: () => pick(k) }, typeof v === "string" ? v : v.name)));
  const head = (n, t) => [h("div", { class: "wz-step", text: `Шаг ${n} из 5` }), h("h3", { text: t })];
  const urlOk = () => {
    try { const u = new URL(/^https?:\/\//i.test(w.url.trim()) ? w.url.trim() : "https://" + w.url.trim()); return !!w.platform && PLATFORMS[w.platform].hosts.includes(u.hostname.toLowerCase()) && u.pathname.length > 1; } catch { return false; }
  };

  function draw() {
    let body;
    if (w.step === 1) {
      const url = h("input", { value: w.url, placeholder: w.platform ? PLATFORMS[w.platform].example : "Сначала выберите, где снимаете", maxlength: 300, inputmode: "url", autocomplete: "off", autocapitalize: "off" });
      const ex = h("div", { class: "hint", text: w.platform ? "Пример ссылки: " + PLATFORMS[w.platform].example : "Выберите платформу — покажем, как выглядит ссылка." });
      const next = h("button", { class: "btn btn-primary", type: "button", onclick: () => { w.step = 2; draw(); } }, "Дальше");
      const sync = () => { w.url = url.value; next.disabled = !urlOk(); };
      url.addEventListener("input", sync); next.disabled = !urlOk();
      body = [...head(1, "Где вы снимаете?"), choice(PLATFORMS, w.platform, (k) => { w.platform = k; draw(); }),
        h("label", { class: "field" }, "Ссылка на ваш канал", url), ex, h("div", { class: "wz-nav" }, next)];
    } else if (w.step === 2) {
      body = [...head(2, "По какому режиму в Roblox снимаете?"), choice(GAMES, w.game, (k) => { w.game = k; draw(); }), nav(() => { w.step = 1; draw(); }, () => { w.step = 3; draw(); }, "Дальше", !!w.game)];
    } else if (w.step === 3) {
      body = [...head(3, "На каком языке снимаете?"), choice(LANGS, w.lang, (k) => { w.lang = k; draw(); }), nav(() => { w.step = 2; draw(); }, () => { w.step = 4; draw(); }, "Дальше", !!w.lang)];
    } else if (w.step === 4) {
      body = [...head(4, "Важно перед продолжением"),
        h("div", { class: "wz-card" },
          h("p", {}, "Магазин ", h("b", { text: "ChapaShop" }), " не предоставляет никакой оплаты блогерам."),
          h("p", { text: "Промокод предоставляет скидку на товары, но не предоставляет оплату блогерам." }),
          h("p", { text: "Чем больше людей вводит ваш промокод, тем больше скидка. Заявку можно отправлять раз в 7 дней.", class: "hint" })),
        nav(() => { w.step = 3; draw(); }, () => { w.step = 5; draw(); }, "Продолжить анкету")];
    } else if (w.step === 5) {
      const code = h("input", { value: w.code, placeholder: "CHAPIK", maxlength: 20, autocapitalize: "characters", autocomplete: "off" });
      const contact = h("input", { value: w.contact, placeholder: "@username", maxlength: 33, autocapitalize: "off", autocomplete: "off" });
      const err = h("div", { class: "err" });
      const next = h("button", { class: "btn btn-primary", type: "button", onclick: () => { w.step = 6; draw(); } }, "Дальше");
      const sync = () => {
        w.code = code.value.trim().toUpperCase(); w.contact = contact.value.trim();
        const codeOk = /^[A-Z0-9]{3,20}$/.test(w.code), cOk = /^@?[A-Za-z0-9_]{5,32}$/.test(w.contact);
        err.textContent = w.code && !codeOk ? "Название: только английские буквы и цифры, 3–20 символов" : (w.contact && !cOk ? "Юзернейм: от 5 символов, латиница, цифры и _" : "");
        next.disabled = !(codeOk && cOk);
      };
      code.addEventListener("input", () => { code.value = code.value.toUpperCase(); sync(); }); contact.addEventListener("input", sync); sync();
      body = [...head(5, "Название промокода и связь"),
        h("label", { class: "field" }, "Название промокода (английские буквы и цифры)", code), h("div", { class: "hint", text: "Например: CHAPIK или CHAPIK2026. Иначе заявка не будет засчитана." }),
        h("label", { class: "field" }, "Ваш юзернейм в Telegram для связи", contact), err,
        h("div", { class: "wz-nav" }, h("button", { class: "btn", type: "button", onclick: () => { w.step = 4; draw(); } }, "Назад"), next)];
    } else if (w.step === 6) {
      const row = (k, v) => h("div", { class: "wz-sum" }, h("span", { text: k }), h("b", { text: v }));
      const msg = h("div", { class: "err" });
      const send = h("button", { class: "btn btn-primary", type: "button", onclick: async () => {
        send.disabled = true; msg.textContent = "";
        try {
          st = await api("/api/promo-requests", { method: "POST", body: JSON.stringify({ platform: w.platform, channel_url: w.url.trim(), game: w.game, language: w.lang, code: w.code, contact: w.contact }) });
          w.step = 7; draw();
        } catch (x) { msg.textContent = x.message; send.disabled = false; }
      } }, "Отправить заявку");
      body = [h("h3", { text: "Проверьте заявку" }),
        h("div", { class: "wz-card" }, row("Платформа", PLATFORMS[w.platform].name), row("Канал", w.url.trim()), row("Режим", GAMES[w.game]), row("Язык", LANGS[w.lang]), row("Промокод", w.code), row("Связь", w.contact.startsWith("@") ? w.contact : "@" + w.contact)),
        h("p", { class: "hint", text: "Промокод даёт покупателям скидку на товары, но не оплату блогеру." }), msg,
        h("div", { class: "wz-nav" }, h("button", { class: "btn", type: "button", onclick: () => { w.step = 5; draw(); } }, "Назад"), send)];
    } else {
      body = [h("div", { class: "wz-done" }, h("div", { class: "wz-ok", text: "✓" }), h("h3", { text: "Заявка отправлена" }),
        h("p", { text: "Мы рассмотрим её и напишем вам в Telegram. Следующую заявку можно отправить через 7 дней." }),
        h("a", { class: "btn btn-primary", href: "/", "data-link": true }, "В магазин"))];
    }
    box.replaceChildren(...body);
  }
  const intro = [h("h2", { class: "title", text: "Свой промокод" }), statusCard()];
  if (st.can_apply) { draw(); view.replaceChildren(...intro, box); }
  else view.replaceChildren(...intro, h("a", { class: "btn", href: "/", "data-link": true }, "В магазин"));
}

// ---------- Маршрутизация ----------
function route() {
  updateBadge();
  const path = location.pathname;
  const tab = path.startsWith("/cart") ? "cart" : path.startsWith("/about") ? "about" : path.startsWith("/orders") ? "orders" : path.startsWith("/profile") ? "profile" : "home";
  document.querySelectorAll(".tabbar a").forEach((a) => a.classList.toggle("on", a.dataset.tab === tab));
  window.scrollTo(0, 0);
  const m = path.match(/^\/product\/(\d+)$/);
  if (m) return pageProduct(+m[1]);
  if (path === "/cart") return pageCart();
  if (path === "/about") return pageAbout();
  if (path === "/promo") return pagePromo();
  const om = path.match(/^\/orders\/(\d+)$/);
  if (om) return pageOrder(+om[1]);
  if (path === "/orders") return pageOrders();
  if (path === "/profile") return pageProfile();
  if (TG && TG.BackButton) { path === "/" || path === "/app" ? TG.BackButton.hide() : TG.BackButton.show(); }
  return pageHome();
}
function go(url) { history.pushState(null, "", url); route(); }
document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-link]");
  if (!a || e.metaKey || e.ctrlKey) return;
  e.preventDefault(); go(a.getAttribute("href"));
});
window.addEventListener("popstate", route);
window.addEventListener("storage", updateBadge);

let st;
$("#search").addEventListener("input", (e) => {
  clearTimeout(st);
  st = setTimeout(() => {
    state.q = e.target.value.trim();
    if (location.pathname !== "/") go("/"); else pageHome.reload && pageHome.reload();
  }, 250);
});

(async () => {
  updateBadge();
  if (TG) {
    TG.ready(); TG.expand();
    document.body.classList.add("in-tg");
    document.querySelectorAll(".tg-only").forEach((e) => (e.hidden = false));
    document.querySelectorAll(".web-only").forEach((e) => (e.hidden = true));
    TG.BackButton.onClick(() => history.length > 1 ? history.back() : go("/"));
    api("/api/me").then((m) => (state.me = m)).catch(() => {});
  }
  try { [state.cats, state.shop] = await Promise.all([api("/api/categories"), api("/api/shop")]); } catch {}
  const bot = state.shop.bot_username;
  document.querySelectorAll(".tg-link").forEach((a) => { a.href = bot ? `https://t.me/${bot}` : "#"; });
  route();
})();
})();
