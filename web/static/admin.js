// ChapaShop — панель владельца. Один файл, без сторонних библиотек.
// Что здесь есть:
//   1. вспомогательные функции (api, окна подтверждения, уведомления);
//   2. вход и выход (форма входа полностью скрывается после авторизации);
//   3. вкладки (переключаются через #адрес, страница НЕ перезагружается);
//   4. разделы: Сводка, Заказы (+страница заказа), Товары, Промокоды, Покупатели, Настройки, Журнал, Копии.
// Все данные берутся из реального API /admin/api/*. Любой текст из базы выводится через esc() — защита от XSS.
(() => {
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const view = $("#view");
let csrf = "";            // CSRF-токен: приходит при входе и отправляется с каждым изменяющим запросом
let navSeq = 0;           // номер текущего перехода — чтобы медленный ответ не затёр новую вкладку

// ---------- Справочники ----------
const STATUS = {awaiting_payment:"Ожидает оплаты", paid:"Оплачен", processing:"В обработке", awaiting_delivery:"Ожидает выдачи", delivered:"Выдан", rejected:"Отклонён", refunded:"Возврат оформлен"};
const NEXT = {awaiting_payment:["rejected"], paid:["processing","awaiting_delivery","delivered","rejected"], processing:["awaiting_delivery","delivered","rejected"], awaiting_delivery:["processing","delivered","rejected"]};
const PAY = {pending:"Ожидает оплаты", paid:"Оплачен", refunded:"Возврат оформлен", failed:"Ошибка оплаты"};
const ACTIONS = {login:"Вход", login_failed:"Неудачный вход", logout:"Выход", password_changed:"Смена пароля", order_status:"Статус заказа", order_server_link:"Ссылка на сервер", order_refund:"Возврат", product_create:"Новый товар", product_update:"Изменение товара", product_delete:"Удаление товара", settings_update:"Настройки", order_deliver:"Начата выдача", order_receipt_sent:"Отправлен чек", backup_create:"Резервная копия", backup_restore:"Восстановление из копии", promo_create:"Новый промокод", promo_update:"Изменение промокода", promo_delete:"Удаление промокода", user_block:"Блокировка покупателя", user_unblock:"Разблокировка покупателя", image_upload:"Загружено фото", demo_products_create:"Добавлены тестовые товары", demo_products_delete:"Удалены тестовые товары", promo_request_approve:"Заявка на промокод одобрена", promo_request_reject:"Заявка на промокод отклонена"};
const SETTING_RU = {shop_name:"Название магазина", shop_description:"Описание", primary_color:"Основной цвет", maintenance_mode:"Режим обслуживания (0/1)", contact_info:"Контакты", order_rules:"Правила заказа", bot_username:"Username бота (без @)", vip_server_link:"Ссылка на VIP-сервер Roblox (покупатель увидит её после оплаты)"};
const GLYPH = {pets:"🐾", eggs:"🥚", potions:"🧪", other:"🎁"};

// ---------- Мелочи ----------
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const dt = (s) => new Date(s).toLocaleString("ru-RU", {dateStyle:"short", timeStyle:"short"});
const stars = (n) => (n === 0 ? "Бесплатно" : `${n} ⭐`);
const badge = (s, big) => `<span class="badge ${esc(s)}${big ? " lg" : ""}">${esc(STATUS[s] || s)}</span>`;
const fresh = () => { const my = navSeq; return () => my === navSeq; };

let toastT;
function toast(text, bad) {
  const el = $("#toast");
  el.textContent = text; el.classList.toggle("bad", !!bad); el.classList.add("on");
  clearTimeout(toastT); toastT = setTimeout(() => el.classList.remove("on"), bad ? 4200 : 2600);
}

// Запрос к API. Тело-объект уходит как JSON, тело-Blob (фото) — как есть. CSRF-токен добавляется всегда.
async function api(path, opts = {}) {
  const headers = {"X-CSRF-Token": csrf};
  let body = opts.body;
  if (body !== undefined && !(body instanceof Blob)) { headers["Content-Type"] = "application/json"; body = JSON.stringify(body); }
  if (opts.type) headers["Content-Type"] = opts.type;
  const r = await fetch("/admin/api" + path, {method: opts.method || "GET", credentials: "same-origin", headers, body});
  if (r.status === 401 && path !== "/login") { showLogin(); throw new Error("Нужен вход"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    let msg = data.detail;
    if (Array.isArray(msg)) msg = msg.map((d) => (d.msg || "").replace("Value error, ", "")).join("; ");
    throw new Error(msg || "Ошибка " + r.status);
  }
  return data;
}
// Кнопка на время запроса «замирает» (нет двойных нажатий), ошибки показываются уведомлением.
function bind(btn, fn) {
  if (!btn) return;
  btn.onclick = async () => {
    if (btn.classList.contains("busy")) return;
    btn.classList.add("busy");
    try { await fn(); } catch (e) { toast(e.message || "Ошибка", true); } finally { btn.classList.remove("busy"); }
  };
}

// ---------- Окна ----------
const modal = $("#modal");
let modalCancel = null;
function openModal(html, onCancel) {
  modal.innerHTML = `<div class="sheet">${html}</div>`;
  modal.classList.remove("hidden"); document.body.style.overflow = "hidden";
  modalCancel = onCancel || closeModal;
  return modal.firstElementChild;
}
function closeModal() { modal.classList.add("hidden"); modal.innerHTML = ""; document.body.style.overflow = ""; modalCancel = null; }
modal.addEventListener("click", (e) => { if (e.target === modal && modalCancel) modalCancel(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && modalCancel) modalCancel(); });

// Свой «confirm/prompt»: в Telegram и Safari стандартные окна часто блокируются.
// Возвращает: true/строку — подтвердили, null — отмена.
function ask({title, text = "", input = null, ok = "Подтвердить", danger = false}) {
  return new Promise((resolve) => {
    const done = (v) => { closeModal(); resolve(v); };
    const sheet = openModal(`<h3>${esc(title)}</h3>${text ? `<p>${esc(text)}</p>` : ""}
      ${input ? `<label class="fld">${esc(input.label || "")}<input id="askIn" maxlength="${input.max || 500}" placeholder="${esc(input.placeholder || "")}" value="${esc(input.value || "")}"></label>` : ""}
      <div class="actions"><button class="btn out" id="askNo">Отмена</button><button class="btn${danger ? " danger" : ""}" id="askOk">${esc(ok)}</button></div>`, () => done(null));
    const inp = $("#askIn", sheet);
    $("#askNo", sheet).onclick = () => done(null);
    $("#askOk", sheet).onclick = () => done(inp ? inp.value : true);
    if (inp) { inp.focus(); inp.addEventListener("keydown", (e) => { if (e.key === "Enter") done(inp.value); }); }
  });
}

// ---------- Вход / выход ----------
function setView(v) {
  $("#boot").classList.add("off");
  $("#login").classList.toggle("hidden", v !== "login");
  $("#app").classList.toggle("hidden", v !== "app");     // после входа форма входа скрыта полностью
}
function showLogin() { closeModal(); setView("login"); }
function showApp() { setView("app"); route(); }

$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target), btn = $("#loginBtn"), err = $("#loginErr");
  err.textContent = ""; btn.classList.add("busy");
  try {
    const d = await api("/login", {method:"POST", body:{username:f.get("username"), password:f.get("password")}});
    csrf = d.csrf; e.target.reset(); showApp();
  } catch (x) { err.textContent = x.message; }
  finally { btn.classList.remove("busy"); }
});
$("#logout").onclick = async () => {
  try { await api("/logout", {method:"POST"}); } catch (e) { /* уже вышли */ }
  csrf = ""; location.hash = ""; showLogin();
};

// ---------- Вкладки ----------
window.addEventListener("hashchange", () => { if (!$("#app").classList.contains("hidden")) route(); });
function route() {
  const [tab, id] = (location.hash.slice(1) || "dash").split("/");
  $$("#tabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === tab));
  const pages = {dash, orders: () => id ? order(id) : orders(), products, promos, requests, customers: () => id ? customer(id) : customers(), settings, audit, backup};
  navSeq++;
  window.scrollTo(0, 0);
  const el = $("#tabs a.on"); if (el && el.scrollIntoView) el.scrollIntoView({inline:"center", block:"nearest"});
  (pages[tab] || dash)().catch((e) => { if (e.message !== "Нужен вход") { view.innerHTML = `<div class="card empty">Не удалось загрузить: ${esc(e.message)}</div>`; toast(e.message, true); } });
}

// ================= СВОДКА =================
async function dash() {
  const ok = fresh();
  const [s, wait] = await Promise.all([api("/stats"), api("/orders?status=paid&limit=5")]);
  if (!ok()) return;
  const max = Math.max(1, ...s.daily.map((d) => d.orders));
  const per = (t, x) => `<div class="card stat"><small>${t}</small><b>${x.orders}</b>заказов · ${x.stars} ⭐</div>`;
  view.innerHTML = `<h2>Сводка</h2>
    ${wait.length ? `<div class="card" style="margin-bottom:14px"><h3>Оплачены — ждут выдачи (${s.by_status.paid || wait.length})</h3><div class="list">${wait.map(orderRow).join("")}</div></div>` : ""}
    <div class="grid">
      <div class="card stat"><small>Всего заказов</small><b>${s.orders_total}</b></div>
      <div class="card stat"><small>Получено</small><b>${s.revenue_stars} ⭐</b></div>
      <div class="card stat"><small>Средний чек</small><b>${s.avg_check} ⭐</b></div>
      <div class="card stat"><small>Покупателей</small><b>${s.customers}</b></div>
      <a class="card stat" href="#customers"><small>Заблокировано</small><b>${s.blocked_users}</b></a>
      <a class="card stat" href="#promos"><small>Промокодов применено</small><b>${s.promo_uses}</b></a>
      <a class="card stat" href="#requests"><small>Новых заявок на промокод</small><b>${s.promo_requests_pending || 0}</b></a>
    </div>
    <h3 style="margin:20px 0 10px">За период</h3>
    <div class="grid">${per("Сегодня", s.periods.today)}${per("7 дней", s.periods.week)}${per("30 дней", s.periods.month)}</div>
    <div class="two" style="margin-top:18px">
      <div class="card"><h3>Заказы за 14 дней</h3><div class="chart">${s.daily.map((d) => `<div class="col" title="${esc(d.date)}: ${d.orders} зак., ${d.stars} ⭐"><i style="height:${Math.max(3, Math.round(d.orders / max * 100))}%"></i><span>${esc(d.date.slice(8))}</span></div>`).join("")}</div></div>
      <div class="card"><h3>Популярные товары</h3>${s.top_products.length ? `<table>${s.top_products.map((t) => `<tr><td>${esc(t.name)}</td><td class="tr">${t.qty} шт.</td><td class="tr">${t.stars} ⭐</td></tr>`).join("")}</table>` : '<p class="muted">Оплаченных заказов пока нет</p>'}</div>
    </div>
    <h3 style="margin:20px 0 10px">Заказы по статусам</h3>
    <div class="grid">${Object.keys(STATUS).map((k) => `<a class="card stat" href="#orders" data-st="${k}"><small>${STATUS[k]}</small><b>${s.by_status[k] || 0}</b></a>`).join("")}</div>`;
  $$("[data-st]", view).forEach((a) => a.addEventListener("click", () => sessionStorage.setItem("st", a.dataset.st)));
}

// ================= ЗАКАЗЫ =================
function orderRow(o) {
  return `<a class="card row" href="#orders/${o.id}">
    <div class="num">${esc(o.number)}</div>
    <div class="mid"><b>${esc(o.roblox_username)}</b><div class="muted small ellip">${esc(o.items_preview || "")}</div><div class="muted small">${dt(o.created_at)} · TG ${esc(o.telegram_id)}</div></div>
    <div class="end"><b>${stars(o.total_stars)}</b>${badge(o.status)}</div></a>`;
}

async function orders() {
  const ok = fresh();
  let st = sessionStorage.getItem("st") || ""; sessionStorage.removeItem("st");
  let vip = ""; try { vip = (await api("/settings")).settings.vip_server_link || ""; } catch {}
  view.innerHTML = `<div class="page-head"><h2>Заказы</h2></div>
    <div class="card" style="margin-bottom:12px"><label class="fld" style="margin:0">🎮 Ссылка на VIP-сервер (покупатель увидит кнопку «Зайти на сервер» после оплаты)<input id="vip" maxlength="512" placeholder="https://www.roblox.com/share?code=..." value="${esc(vip)}" autocomplete="off" autocapitalize="off"></label>
      <div class="actions"><button class="btn" id="vipsave">Сохранить ссылку</button></div></div>
    <div class="bar"><input id="oq" type="search" placeholder="Номер, Telegram ID или Roblox ник"></div>
    <div class="chips" id="ochips"></div><div id="olist" class="list"></div>`;
  const chips = () => {
    $("#ochips").innerHTML = [["", "Все"], ...Object.entries(STATUS)].map(([k, v]) => `<button class="chip${k === st ? " on" : ""}" data-s="${k}">${esc(v)}</button>`).join("");
    $$(".chip", view).forEach((b) => b.onclick = () => { st = b.dataset.s; chips(); load(); });
  };
  const load = async () => {
    try {
      const rows = await api("/orders?" + new URLSearchParams({q: $("#oq").value, status: st}));
      if (!ok()) return;
      $("#olist").innerHTML = rows.length ? rows.map(orderRow).join("") : `<div class="card empty">Заказов нет</div>`;
    } catch (e) { toast(e.message, true); }
  };
  let t; $("#oq").oninput = () => { clearTimeout(t); t = setTimeout(load, 300); };
  bind($("#vipsave"), async () => {
    await api("/settings", {method:"PUT", body:{values:{vip_server_link: $("#vip").value.trim()}}});
    toast("Ссылка на VIP-сервер сохранена");
  });
  chips(); await load();
}

// ---------- Страница заказа ----------
async function order(id) {
  const ok = fresh();
  const o = await api("/orders/" + encodeURIComponent(id));
  if (!ok()) return;
  const next = NEXT[o.status] || [];
  const canGive = ["paid", "processing", "awaiting_delivery"].includes(o.status);
  const canLink = canGive || o.status === "delivered";
  const canReject = ["awaiting_payment", "paid", "processing", "awaiting_delivery"].includes(o.status);
  const hasPdf = ["paid", "refunded"].includes(o.payment_status);
  const kv = (k, v) => `<div><span>${k}</span><b>${v}</b></div>`;
  const tg = o.customer && o.customer.username ? ` <span class="muted">@${esc(o.customer.username)}</span>` : "";

  view.innerHTML = `<button class="btn ghost back" id="back">← Назад</button>
  <div class="order-page">
    <!-- ЛЕВАЯ КОЛОНКА: номер, статус, покупатель -->
    <aside class="card ord-left">
      <div class="ord-label">Заказ</div>
      <div class="ord-num">${esc(o.number)}</div>
      ${badge(o.status, true)}
      <div class="kv">
        ${kv("Roblox ник", esc(o.roblox_username))}
        ${kv("Telegram ID", esc(o.telegram_id) + tg)}
        ${o.customer ? kv("Покупатель", `<a href="#customers/${o.customer.id}">${esc(o.customer.first_name || "Профиль")}</a>${o.customer.is_blocked ? ' <span class="badge rejected">заблокирован</span>' : ""}`) : ""}
        ${kv("Дата заказа", dt(o.created_at))}
        ${kv("Оплата", esc(PAY[o.payment_status] || o.payment_status))}
        ${o.server_link ? kv("Ссылка на сервер", `<a href="${esc(o.server_link)}" target="_blank" rel="noopener noreferrer">открыть</a>`) : ""}
      </div>
    </aside>

    <!-- ПРАВАЯ КОЛОНКА: товары и кнопки действий -->
    <section class="list">
      <div class="card">
        <h3>Товары</h3>
        <table class="ord-table"><thead><tr><th>Товар</th><th>Цена</th><th>Кол-во</th><th>Сумма</th></tr></thead>
          <tbody>${o.items.map((i) => `<tr><td>${esc(i.name)}</td><td>${stars(i.price_stars)}</td><td>${i.quantity}</td><td><b>${stars(i.subtotal)}</b></td></tr>`).join("")}</tbody></table>
        <div class="totals">
          ${o.discount_stars ? `<div class="disc"><span>Скидка (${esc(o.promo_code || "промокод")})</span><span>−${stars(o.discount_stars)}</span></div>` : ""}
          <div class="sum"><span>Итого</span><span>${stars(o.total_stars)}</span></div>
        </div>
        <div class="act-grid">
          <button class="btn${canLink ? "" : " dis"}" id="a-link">Скинуть ссылку на сервер</button>
          <button class="btn${canGive ? "" : " dis"}" id="a-give">Отдать заказ</button>
          <button class="btn danger${canReject ? "" : " dis"}" id="a-rej">Отклонить заказ</button>
          ${hasPdf ? `<a class="btn out" id="a-pdf" href="/admin/api/orders/${o.id}/receipt.pdf?download=1" download>Сохранить PDF-чек</a>` : `<button class="btn dis" title="Чек появится после оплаты">Сохранить PDF-чек</button>`}
        </div>
        <div id="linkbox" class="linkbox hidden">
          <label class="fld" style="margin:0">Ссылка на приватный сервер (https://…)<input id="lnk" maxlength="512" placeholder="https://www.roblox.com/share?code=..." value="${esc(o.server_link || o.default_server_link || "")}"></label>
          <button class="btn" id="lgo">Отправить покупателю</button>
        </div>
        ${canGive || canReject ? "" : `<p class="note">Действия недоступны: ${o.status === "awaiting_payment" ? "заказ ещё не оплачен" : "заказ завершён"}.</p>`}
        ${o.status === "awaiting_payment" ? '<p class="note">Выдать можно только оплаченный заказ — оплату отмечает Telegram автоматически.</p>' : ""}
      </div>

      ${next.length ? `<div class="card"><h3>Другой статус</h3><select id="nst">${next.map((s) => `<option value="${s}">${STATUS[s]}</option>`).join("")}</select>
        <label class="fld">Комментарий (для отклонения — причина)<textarea id="ncm" maxlength="500"></textarea></label>
        <label class="chk"><input type="checkbox" id="nnt" checked> Уведомить покупателя в Telegram</label>
        <div class="actions"><button class="btn" id="nsave">Сохранить статус</button></div></div>` : ""}

      <div class="two">
        <div class="card"><h3>История статусов</h3><table>${o.history.map((h) => `<tr><td class="small">${dt(h.at)}</td><td>${esc(h.new_ru)}<div class="muted small">${esc(h.by)}${h.comment ? " · " + esc(h.comment) : ""}</div></td></tr>`).join("")}</table></div>
        <div class="list">
          <div class="card"><h3>Платежи</h3>${o.payments.length ? `<table>${o.payments.map((p) => `<tr><td class="small">${dt(p.at)}</td><td>${p.amount} ⭐</td><td>${esc(p.status)}</td></tr><tr><td colspan="3" class="mono">${esc(p.charge_id)}</td></tr>`).join("")}</table>` : '<p class="muted">Оплаты пока нет</p>'}</div>
          ${hasPdf ? `<div class="card"><h3>Чек</h3><p class="muted small">PDF также можно отправить покупателю в чат с ботом.</p><div class="actions"><a class="btn ghost" href="/admin/api/orders/${o.id}/receipt.pdf" target="_blank" rel="noopener">Открыть</a><button class="btn" id="rcp">Отправить покупателю</button></div></div>` : ""}
          ${o.payment_status === "paid" ? `<div class="card"><h3>Возврат</h3><p class="muted small">Stars вернутся покупателю через Telegram.</p><div class="actions"><button class="btn danger" id="rf">Оформить возврат</button></div></div>` : ""}
        </div>
      </div>
    </section>
  </div>`;

  const reload = () => order(id);
  const sentText = (r, yes, no) => r.notified ? yes : no;
  $("#back").onclick = () => { location.hash = "#orders"; };

  // 1) Скинуть ссылку на сервер: раскрывает поле; «Отправить» делает POST и пишет покупателю в Telegram
  $("#a-link").onclick = () => { if (canLink) { $("#linkbox").classList.toggle("hidden"); $("#lnk").focus(); } };
  bind($("#lgo"), async () => {
    const link = $("#lnk").value.trim();
    if (!link.startsWith("https://")) throw new Error("Ссылка должна начинаться с https://");
    const r = canGive ? await api(`/orders/${o.id}/deliver`, {method:"POST", body:{server_link: link}})
                      : await api(`/orders/${o.id}/server-link`, {method:"POST", body:{server_link: link, notify:true}});
    toast(sentText(r, "Ссылка отправлена покупателю", "Ссылка сохранена, но сообщение не отправлено (бот не подключён?)")); await reload();
  });
  // 2) Отдать заказ
  bind($("#a-give"), async () => {
    if (!canGive) return;
    if (!(await ask({title: `Отдать заказ ${o.number}?`, text: "Заказ станет «Выдан», покупатель получит уведомление и PDF-чек.", ok: "Отдать"}))) return;
    const r = await api(`/orders/${o.id}/status`, {method:"POST", body:{status:"delivered", notify:true}});
    toast(sentText(r, "Заказ выдан, покупатель уведомлён", "Заказ выдан (уведомление не отправлено)")); await reload();
  });
  // 3) Отклонить заказ
  bind($("#a-rej"), async () => {
    if (!canReject) return;
    const reason = await ask({title: `Отклонить заказ ${o.number}?`, text: "Покупатель увидит причину.", input: {label: "Причина (необязательно)", max: 500}, ok: "Отклонить", danger: true});
    if (reason === null) return;
    const r = await api(`/orders/${o.id}/status`, {method:"POST", body:{status:"rejected", comment: reason.trim() || null, notify:true}});
    toast(sentText(r, "Заказ отклонён, покупатель уведомлён", "Заказ отклонён")); await reload();
  });
  if (next.length) bind($("#nsave"), async () => {
    const r = await api(`/orders/${o.id}/status`, {method:"POST", body:{status:$("#nst").value, comment:$("#ncm").value || null, notify:$("#nnt").checked}});
    toast(sentText(r, "Статус сохранён, покупатель уведомлён", "Статус сохранён")); await reload();
  });
  bind($("#rcp"), async () => {
    const r = await api(`/orders/${o.id}/send-receipt`, {method:"POST"});
    toast(r.notified ? "Чек отправлен покупателю" : "Чек не отправлен (бот не подключён)");
  });
  bind($("#rf"), async () => {
    if (!(await ask({title: `Вернуть ${o.total_stars} ⭐?`, text: "Stars вернутся покупателю через Telegram. Действие нельзя отменить.", ok: "Вернуть", danger: true}))) return;
    await api(`/orders/${o.id}/refund`, {method:"POST"}); toast("Возврат оформлен"); await reload();
  });
}

// ================= ТОВАРЫ =================
// Фото из галереи: сжимаем в браузере (до 1000 px), чтобы загрузка с телефона была быстрой.
const toBlob = (c, type, q) => new Promise((res) => c.toBlob(res, type, q));
async function prepareImage(file) {
  // Тип у файлов из галереи бывает пустым (Android, Google Фото) — поэтому смотрим ещё и на расширение.
  const ext = (file.name.match(/\.([a-z0-9]+)$/i) || [,""])[1].toLowerCase();
  const rawOk = /^(jpe?g|png|webp|gif)$/.test(ext) || /^image\/(jpeg|png|webp|gif)$/.test(file.type);
  const heic = /^(heic|heif)$/.test(ext) || /heic|heif/.test(file.type);
  if (file.type && !/^image\//.test(file.type) && !rawOk) throw new Error("Выберите картинку (JPG, PNG, WEBP)");
  const url = URL.createObjectURL(file);
  try {
    let img;
    try {
      img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error("decode")); i.src = url; });
    } catch (e) {
      // браузер не смог открыть фото: если это обычный JPG/PNG/WEBP/GIF до 5 МБ — отправим как есть, сервер проверит сам
      if (rawOk && !heic && file.size <= 5 * 1024 * 1024) return file;
      throw new Error(heic ? "Фото в формате HEIC не открывается. В галерее выберите другое или сделайте скриншот фото." : "Не удалось прочитать фото. Выберите JPG или PNG.");
    }
    const k = Math.min(1, 1000 / Math.max(img.naturalWidth, img.naturalHeight));
    const w = Math.max(1, Math.round(img.naturalWidth * k)), h = Math.max(1, Math.round(img.naturalHeight * k));
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    const ctx = c.getContext("2d");
    let blob = null;
    if (file.type === "image/png" || file.type === "image/webp" || ext === "png" || ext === "webp") {     // сохраняем прозрачность
      ctx.drawImage(img, 0, 0, w, h);
      blob = await toBlob(c, "image/png");
      if (blob && blob.size > 1.2 * 1024 * 1024) blob = null;
    }
    if (!blob) {
      ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, w, h); ctx.drawImage(img, 0, 0, w, h);
      for (const q of [0.88, 0.78, 0.65]) { blob = await toBlob(c, "image/jpeg", q); if (blob && blob.size < 900 * 1024) break; }
    }
    if (!blob) { if (rawOk && file.size <= 5 * 1024 * 1024) return file; throw new Error("Не удалось подготовить фото"); }
    return blob;
  } finally { URL.revokeObjectURL(url); }
}

function thumb(p, cats) {
  const slug = (cats.find((c) => c.id === p.category_id) || {}).slug;
  return p.image_url ? `<img src="${esc(p.image_url)}" alt="" loading="lazy">` : `<span>${GLYPH[slug] || "★"}</span>`;
}

async function products() {
  const ok = fresh();
  const {products: list, categories: cats} = await api("/products");
  if (!ok()) return;
  const catName = Object.fromEntries(cats.map((c) => [c.id, c.name]));
  const demoCount = list.filter((p) => p.is_demo).length;
  view.innerHTML = `<div class="page-head"><h2>Товары</h2><button class="btn" id="padd">+ Добавить товар</button></div>
    <div class="bar"><input id="pq" type="search" placeholder="Поиск товара"></div>
    <div id="plist" class="pgrid"></div>
    <div class="card demo-box" style="margin-top:18px"><h3>Тестовые товары</h3>
      <p class="muted small">Фейковые товары с пометкой «Демо» — чтобы проверить магазин, корзину и бота. Один из них со скидкой, один «нет в наличии». Реальные товары не затрагиваются.</p>
      <div class="actions"><button class="btn ghost" id="demoAdd">+ Добавить тестовые товары</button>
      <button class="btn out" id="demoDel"${demoCount ? "" : " disabled"}>Удалить тестовые (${demoCount})</button></div></div>`;

  const draw = () => {
    const q = $("#pq").value.trim().toLowerCase();
    const rows = list.filter((p) => p.name.toLowerCase().includes(q));
    $("#plist").innerHTML = rows.map((p) => `<div class="card pcard" data-id="${p.id}">
      <div class="pimg">${thumb(p, cats)}${p.old_price_stars ? `<span class="disc">−${p.discount_percent}%</span>` : ""}</div>
      <div class="pbody"><div class="pname">${esc(p.name)}</div>
        <div class="pprice">${stars(p.price_stars)}${p.old_price_stars ? `<s>${p.old_price_stars}</s>` : ""}</div>
        <div class="muted small">${esc(catName[p.category_id] || "Без категории")}</div>
        <div class="ptags">${p.is_demo ? '<span class="badge">Демо</span>' : ""}${p.is_hidden ? '<span class="badge rejected">Скрыт</span>' : ""}${!p.in_stock ? '<span class="badge awaiting_payment">Нет в наличии</span>' : ""}${p.stock != null ? `<span class="badge">Осталось: ${p.stock}</span>` : ""}</div></div></div>`).join("")
      || `<div class="card empty" style="grid-column:1/-1">Товаров нет. Нажмите «+ Добавить товар».</div>`;
    $$("[data-id]", $("#plist")).forEach((el) => el.onclick = () => form(list.find((p) => p.id == el.dataset.id)));
  };
  $("#pq").oninput = draw; draw();
  $("#padd").onclick = () => form();
  bind($("#demoAdd"), async () => { const r = await api("/demo-products", {method:"POST"}); toast(r.created ? `Добавлено тестовых товаров: ${r.created}` : "Тестовые товары уже добавлены"); await products(); });
  bind($("#demoDel"), async () => {
    if (!(await ask({title: "Удалить тестовые товары?", text: "Удалятся только товары с пометкой «Демо». Старые заказы сохранятся.", ok: "Удалить", danger: true}))) return;
    const r = await api("/demo-products", {method:"DELETE"}); toast(`Удалено: ${r.deleted}`); await products();
  });

  // ----- форма добавления / редактирования -----
  function form(p) {
    const isNew = !p;
    p = p || {name:"", description:"", image_url:"", category_id: cats[0] ? cats[0].id : null, base_price_stars:100, discount_percent:0, is_available:true, is_hidden:false, is_demo:false, stock:null};
    let blob = null, preview = p.image_url || "", removed = false;   // blob — выбранное, но ещё не загруженное фото
    const sheet = openModal(`<h3>${isNew ? "Новый товар" : "Редактирование"}</h3>
      <div class="fld">Фото товара</div>
      <div class="photo"><div class="pimg" id="fprev"></div>
        <div class="btns"><label class="btn" id="fpick" for="ffile" role="button" tabindex="0">Выбрать из галереи</label><button class="btn out sm" id="fclr" type="button">Убрать фото</button></div></div>
      <input type="file" id="ffile" accept="image/*" class="vh">
      <div class="err" id="ferr" role="alert"></div>
      <details class="alt"><summary>Или указать ссылку на картинку</summary><input id="furl" maxlength="512" placeholder="https://…" value="${esc(/^https:/.test(p.image_url || "") ? p.image_url : "")}" style="margin-top:8px"></details>
      <label class="fld">Название<input id="fn" maxlength="128" value="${esc(p.name)}" placeholder="Например, Неон-дракон"></label>
      <label class="fld">Описание (необязательно)<textarea id="fd" maxlength="2000" placeholder="Что входит в товар, особенности">${esc(p.description)}</textarea></label>
      <label class="fld">Категория<select id="fc"><option value="">Без категории</option>${cats.map((c) => `<option value="${c.id}"${c.id === p.category_id ? " selected" : ""}>${esc(c.name)}</option>`).join("")}</select></label>
      <div class="two-in"><label class="fld">Цена без скидки, ⭐ (0 — бесплатно)<input id="fp" type="number" inputmode="numeric" min="0" max="100000" value="${p.base_price_stars}"></label>
        <label class="fld">Скидка, %<input id="fx" type="number" inputmode="numeric" min="0" max="90" value="${p.discount_percent || 0}"></label></div>
      <div class="dchips">${[0, 10, 20, 30, 50].map((d) => `<button class="chip" type="button" data-d="${d}">${d ? "−" + d + "%" : "Без скидки"}</button>`).join("")}</div>
      <div class="pricebox"><span>Покупатель заплатит</span><span id="fres"></span></div>
      <label class="fld">Сколько штук в наличии (пусто — без ограничения)<input id="fst" type="number" inputmode="numeric" min="0" max="1000000" placeholder="Например, 3" value="${p.stock == null ? "" : p.stock}"></label>
      <label class="chk"><input type="checkbox" id="fa"${p.is_available ? " checked" : ""}> В наличии</label>
      <label class="chk"><input type="checkbox" id="fh"${p.is_hidden ? " checked" : ""}> Скрыть из магазина</label>
      <label class="chk"><input type="checkbox" id="fm"${p.is_demo ? " checked" : ""}> Пометка «Демо» (тестовый товар)</label>
      <div class="actions"><button class="btn out" id="fx2" type="button">Отмена</button><button class="btn" id="fs" type="button">Сохранить</button></div>
      ${isNew ? "" : '<div class="actions" style="margin-top:8px"><button class="btn danger sm" id="fdl" type="button" style="flex:none">Удалить товар</button></div>'}`);

    const slugOf = () => (cats.find((c) => String(c.id) === $("#fc", sheet).value) || {}).slug;
    const drawPreview = () => {
      $("#fprev", sheet).innerHTML = preview ? `<img src="${esc(preview)}" alt="">` : `<span>${GLYPH[slugOf()] || "★"}</span>`;
    };
    const calc = () => {
      const base = Math.max(0, parseInt($("#fp", sheet).value, 10) || 0);
      const d = Math.min(90, Math.max(0, parseInt($("#fx", sheet).value, 10) || 0));
      const fin = d ? Math.max(1, Math.round(base * (100 - d) / 100)) : base;
      $("#fres", sheet).innerHTML = d && fin < base ? `<s>${base}</s><b>${fin} ⭐</b>` : `<b>${base} ⭐</b>`;
      $$(".dchips .chip", sheet).forEach((c) => c.classList.toggle("on", +c.dataset.d === d));
    };
    $("#fp", sheet).oninput = calc; $("#fx", sheet).oninput = calc;
    $$(".dchips .chip", sheet).forEach((c) => c.onclick = () => { $("#fx", sheet).value = c.dataset.d; calc(); });
    $("#fc", sheet).onchange = drawPreview;
    $("#fx2", sheet).onclick = closeModal;
    $("#fpick", sheet).onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#ffile", sheet).click(); } };
    $("#fclr", sheet).onclick = () => { blob = null; preview = ""; removed = true; $("#furl", sheet).value = ""; drawPreview(); };
    $("#ffile", sheet).onchange = async (e) => {
      const f = e.target.files[0]; if (!f) return;
      $("#ferr", sheet).textContent = "";
      try {
        blob = await prepareImage(f); removed = false; $("#furl", sheet).value = "";
        preview = URL.createObjectURL(blob); drawPreview(); toast("Фото выбрано");
      } catch (x) { $("#ferr", sheet).textContent = x.message; toast(x.message, true); }
      e.target.value = "";
    };
    bind($("#fs", sheet), async () => {
      const name = $("#fn", sheet).value.trim(), price = parseInt($("#fp", sheet).value, 10);
      if (!name) throw new Error("Введите название товара");
      if (!(price >= 0)) throw new Error("Цена должна быть от 0 ⭐ (0 — бесплатный товар)");
      let image = removed ? null : (p.image_url || null);
      const link = $("#furl", sheet).value.trim();
      if (link) image = link;
      if (blob) {                                                        // сначала загружаем фото, потом сохраняем товар
        toast("Загружаю фото…");
        image = (await api("/upload-image", {method:"POST", body: blob, type: blob.type || "application/octet-stream"})).image_url;
      }
      await api(isNew ? "/products" : "/products/" + p.id, {method: isNew ? "POST" : "PUT", body: {
        name, description: $("#fd", sheet).value, image_url: image,
        category_id: $("#fc", sheet).value ? +$("#fc", sheet).value : null,
        price_stars: price, discount_percent: Math.min(90, Math.max(0, parseInt($("#fx", sheet).value, 10) || 0)),
        stock: $("#fst", sheet).value.trim() === "" ? null : Math.max(0, parseInt($("#fst", sheet).value, 10) || 0),
        is_available: $("#fa", sheet).checked, is_hidden: $("#fh", sheet).checked, is_demo: $("#fm", sheet).checked}});
      closeModal(); toast("Товар сохранён"); await products();
    });
    if (!isNew) bind($("#fdl", sheet), async () => {
      if (!(await ask({title: "Удалить товар?", text: "Старые заказы сохранятся.", ok: "Удалить", danger: true}))) return;
      await api("/products/" + p.id, {method:"DELETE"}); toast("Товар удалён"); await products();
    });
    drawPreview(); calc();
  }
}

// ================= ПОКУПАТЕЛИ =================
async function customers() {
  const ok = fresh();
  view.innerHTML = `<div class="page-head"><h2>Покупатели</h2></div><div class="bar"><input id="cq" type="search" placeholder="Имя, @username, Roblox ник или Telegram ID"></div><div id="clist" class="list"></div>`;
  const load = async () => {
    try {
      const rows = await api("/customers?" + new URLSearchParams({q: $("#cq").value}));
      if (!ok()) return;
      $("#clist").innerHTML = rows.map((u) => `<a class="card row" href="#customers/${u.id}">
        <div class="mid"><b>${esc(u.first_name || "Без имени")}</b> ${u.username ? "@" + esc(u.username) : ""} ${u.is_blocked ? '<span class="badge rejected">заблокирован</span>' : ""}<div class="muted small">TG ${esc(u.telegram_id)} · Roblox: ${esc(u.roblox_username || "—")}</div></div>
        <div class="end"><b>${stars(u.spent_stars)}</b><span class="muted small">${u.orders} заказ(ов)</span></div></a>`).join("") || `<div class="card empty">Покупателей пока нет</div>`;
    } catch (e) { toast(e.message, true); }
  };
  let t; $("#cq").oninput = () => { clearTimeout(t); t = setTimeout(load, 300); };
  await load();
}

async function customer(id) {
  const ok = fresh();
  const u = await api("/customers/" + encodeURIComponent(id));
  if (!ok()) return;
  view.innerHTML = `<button class="btn ghost back" id="back">← Все покупатели</button>
    <div class="card" style="margin-bottom:14px"><h2 style="margin-bottom:6px">${esc(u.first_name || "Покупатель")} ${u.username ? '<span class="muted">@' + esc(u.username) + "</span>" : ""}</h2>
      <div class="kv"><div><span>Telegram ID</span><b>${esc(u.telegram_id)}</b></div><div><span>Roblox ник</span><b>${esc(u.roblox_username || "—")}</b></div></div>
      ${u.is_blocked ? `<p style="margin-top:10px"><span class="badge rejected">Заблокирован</span> ${esc(u.blocked_reason || "")}</p>` : ""}
      <div class="actions"><button class="btn${u.is_blocked ? "" : " danger"}" id="blk">${u.is_blocked ? "Разблокировать" : "Заблокировать"}</button></div></div>
    <h3>Заказы</h3><div class="list">${u.orders.map(orderRow).join("") || '<div class="card empty">Заказов нет</div>'}</div>`;
  $("#back").onclick = () => { location.hash = "#customers"; };
  bind($("#blk"), async () => {
    let reason = null;
    if (!u.is_blocked) {
      reason = await ask({title: "Заблокировать покупателя?", text: "Он не сможет создавать заказы и платить. Старые заказы останутся.", input: {label: "Причина (необязательно)", max: 255}, ok: "Заблокировать", danger: true});
      if (reason === null) return;
    } else if (!(await ask({title: "Разблокировать покупателя?", ok: "Разблокировать"}))) return;
    await api(`/customers/${u.id}/block`, {method:"POST", body:{blocked: !u.is_blocked, reason: (reason || "").trim() || null}});
    toast(u.is_blocked ? "Покупатель разблокирован" : "Покупатель заблокирован"); await customer(id);
  });
}

// ================= ПРОМОКОДЫ =================
async function promos() {
  const ok = fresh();
  const list = await api("/promos");
  if (!ok()) return;
  view.innerHTML = `<div class="page-head"><h2>Промокоды</h2></div><div class="two"><div class="card"><h3>Новый промокод</h3>
    <label class="fld">Название скидки (необязательно)<input id="pt" maxlength="64" placeholder="Например, Скидка для друзей" autocomplete="off"></label>
    <label class="fld">Код, который вводит покупатель (латиница, цифры)<input id="pc" maxlength="32" placeholder="SALE10" autocapitalize="characters" autocomplete="off"></label>
    <label class="fld">Тип скидки<select id="pk"><option value="percent">Процент (1–90%)</option><option value="fixed">Фиксированная (⭐)</option></select></label>
    <label class="fld">Размер скидки<input id="pv" type="number" inputmode="numeric" min="1" placeholder="10"></label>
    <label class="fld">Сколько раз можно использовать (пусто — без лимита)<input id="pm" type="number" inputmode="numeric" min="1" placeholder="100"></label>
    <label class="fld">Рост скидки: +1% за каждые N использований (необязательно, только для %)<input id="pg" type="number" inputmode="numeric" min="1" placeholder="10"></label>
    <label class="fld">Потолок роста, % (необязательно)<input id="px" type="number" inputmode="numeric" min="1" max="90" placeholder="15"></label>
    <div class="actions"><button class="btn" id="padd">Создать</button></div></div>
    <div class="list">${list.map((p) => `<div class="card row"><div class="mid"><b class="mono" style="font-size:15px">${esc(p.code)}</b> ${p.is_active ? "" : '<span class="badge rejected">выключен</span>'}
      ${p.title ? `<div class="small">${esc(p.title)}</div>` : ""}
      <div class="muted small">−${p.percent ? (p.percent_now && p.percent_now !== p.percent ? p.percent_now + "% сейчас (старт " + p.percent + "%)" : p.percent + "%") + (p.growth_every ? ` · +1% за каждые ${p.growth_every}, до ${p.max_percent || p.percent}%` : "") : p.fixed_stars + " ⭐"} · использован ${p.used_count}${p.max_uses ? " из " + p.max_uses : " раз"}</div></div>
      <div class="actions" style="margin:0"><button class="btn ghost sm" data-t="${p.id}">${p.is_active ? "Выключить" : "Включить"}</button><button class="btn danger sm" data-d="${p.id}">Удалить</button></div></div>`).join("") || '<div class="card empty">Промокодов пока нет</div>'}</div></div>`;
  bind($("#padd"), async () => {
    const v = parseInt($("#pv").value, 10), m = parseInt($("#pm").value, 10), fixed = $("#pk").value === "fixed";
    await api("/promos", {method:"POST", body:{code:$("#pc").value, title:$("#pt").value, percent: fixed ? null : v, fixed_stars: fixed ? v : null, max_uses: m || null, growth_every: fixed ? null : (parseInt($("#pg").value, 10) || null), max_percent: fixed ? null : (parseInt($("#px").value, 10) || null)}});
    toast("Промокод создан"); await promos();
  });
  $$("[data-t]", view).forEach((b) => bind(b, async () => {
    const p = list.find((x) => x.id === +b.dataset.t);
    await api("/promos/" + p.id, {method:"PUT", body:{code:p.code, title:p.title, percent:p.percent, fixed_stars:p.fixed_stars, max_uses:p.max_uses, is_active:!p.is_active}}); await promos();
  }));
  $$("[data-d]", view).forEach((b) => bind(b, async () => {
    if (!(await ask({title: "Удалить промокод?", ok: "Удалить", danger: true}))) return;
    await api("/promos/" + b.dataset.d, {method:"DELETE"}); toast("Удалён"); await promos();
  }));
}


// ================= ЗАЯВКИ НА ПРОМОКОД =================
const PLAT = {tiktok: "TikTok", youtube: "YouTube"}, GAME = {murder_mystery: "Murder Mystery", adopt_me: "Adopt Me"}, LANG = {ru: "Русский", uk: "Українська", en: "English"};
const REQ = {pending: ["Новая", "paid"], approved: ["Одобрена", "delivered"], rejected: ["Отклонена", "rejected"]};
async function requests() {
  const ok = fresh();
  const status = ["pending", "approved", "rejected", "all"].includes(location.hash.split("/")[1]) ? location.hash.split("/")[1] : "pending";
  const list = await api("/promo-requests?status=" + encodeURIComponent(status));
  if (!ok()) return;
  const tab = (k, t) => `<a class="btn ${status === k ? "" : "ghost"} sm" href="#requests/${k}">${t}</a>`;
  const link = (u) => (/^https:\/\//.test(u) ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(u)}</a>` : esc(u));
  view.innerHTML = `<div class="page-head"><h2>Заявки на промокод</h2></div>
    <div class="actions" style="margin:0 0 12px;flex-wrap:wrap">${tab("pending", "Новые")}${tab("approved", "Одобренные")}${tab("rejected", "Отклонённые")}${tab("all", "Все")}</div>
    <div class="list">${list.map((r) => { const [lbl, cls] = REQ[r.status] || [r.status, ""]; return `<div class="card" data-r="${r.id}">
      <div class="row" style="justify-content:space-between;gap:8px"><b class="mono" style="font-size:17px">${esc(r.code)}</b><span class="badge ${cls}">${lbl}</span></div>
      <div class="small" style="margin-top:6px;display:grid;gap:3px">
        <div><span class="muted">Платформа:</span> ${esc(PLAT[r.platform] || r.platform)} · ${link(r.channel_url)}</div>
        <div><span class="muted">Режим:</span> ${esc(GAME[r.game] || r.game)} · <span class="muted">Язык:</span> ${esc(LANG[r.language] || r.language)}</div>
        <div><span class="muted">Связь:</span> <a href="https://t.me/${esc(r.contact.replace("@", ""))}" target="_blank" rel="noopener noreferrer">${esc(r.contact)}</a> · <span class="muted">TG ID:</span> ${r.telegram_id}</div>
        <div class="muted">${dt(r.created_at)}${r.decided_by ? ` · решил: ${esc(r.decided_by)}` : ""}</div>
        ${r.status === "approved" ? `<div><b>${r.used_count ?? 0}</b> чел. ввели промокод · скидка сейчас ${r.percent_now || "—"}%</div>` : ""}
        ${r.admin_comment ? `<div class="muted">Причина отказа: ${esc(r.admin_comment)}</div>` : ""}</div>
      ${r.status === "pending" ? `<div class="two-in" style="margin-top:10px">
        <label class="fld">Старт, %<input class="ap" type="number" inputmode="numeric" min="1" max="90" value="5"></label>
        <label class="fld">+1% за каждые N чел.<input class="ag" type="number" inputmode="numeric" min="1" value="10"></label></div>
        <label class="fld">Потолок, %<input class="ax" type="number" inputmode="numeric" min="1" max="90" value="15"></label>
        <label class="fld">Причина отказа (необязательно)<input class="ac" maxlength="255" placeholder="Например, мало подписчиков"></label>
        <div class="actions"><button class="btn sm" data-ok="${r.id}">Одобрить</button><button class="btn danger sm" data-no="${r.id}">Отклонить</button></div>` : ""}</div>`; }).join("") || '<div class="card empty">Заявок нет</div>'}</div>`;
  $$("[data-ok]", view).forEach((b) => bind(b, async () => {
    const c = b.closest("[data-r]"), v = (s) => parseInt($(s, c).value, 10);
    await api(`/promo-requests/${b.dataset.ok}/approve`, {method: "POST", body: {percent: v(".ap"), growth_every: v(".ag"), max_percent: v(".ax")}});
    toast("Одобрено — промокод создан, блогер получил сообщение"); await requests();
  }));
  $$("[data-no]", view).forEach((b) => bind(b, async () => {
    const c = b.closest("[data-r]");
    if (!(await ask({title: "Отклонить заявку?", ok: "Отклонить", danger: true}))) return;
    await api(`/promo-requests/${b.dataset.no}/reject`, {method: "POST", body: {comment: $(".ac", c).value}});
    toast("Отклонено"); await requests();
  }));
}

// ================= НАСТРОЙКИ =================
async function settings() {
  const ok = fresh();
  const {settings: s, secrets} = await api("/settings");
  if (!ok()) return;
  const keys = Object.keys(s);
  view.innerHTML = `<div class="page-head"><h2>Настройки</h2></div><div class="two"><div class="card">
    ${keys.map((k) => `<label class="fld">${esc(SETTING_RU[k] || k)}${(s[k].length > 60 || k.startsWith("text_") || k.startsWith("notify_")) ? `<textarea data-k="${esc(k)}" maxlength="4000">${esc(s[k])}</textarea>` : `<input data-k="${esc(k)}" maxlength="4000" value="${esc(s[k])}">`}</label>`).join("")}
    <div class="actions"><button class="btn" id="ss">Сохранить настройки</button></div></div>
    <div class="list"><div class="card"><h3>Секреты сервера</h3><p class="muted small" style="margin-bottom:8px">Меняются только в Render → Environment.</p>
      ${Object.entries(secrets).map(([k, v]) => `<div class="okline"><span>${v ? "✅" : "❌"}</span><b>${esc(k)}</b><span class="muted">${v ? "настроен" : "не задан"}</span></div>`).join("")}</div>
    <div class="card"><h3>Смена пароля</h3>
      <label class="fld">Старый пароль<input id="op" type="password" autocomplete="current-password"></label>
      <label class="fld">Новый пароль (от 8 символов)<input id="np" type="password" autocomplete="new-password"></label>
      <div class="actions"><button class="btn" id="cp">Сменить пароль</button></div></div></div></div>`;
  bind($("#ss"), async () => {
    const values = {}; $$("[data-k]", view).forEach((el) => values[el.dataset.k] = el.value);
    const r = await api("/settings", {method:"PUT", body:{values}});
    toast(r.changed.length ? "Сохранено: " + r.changed.length : "Изменений нет");
  });
  bind($("#cp"), async () => {
    const r = await api("/password", {method:"POST", body:{old_password:$("#op").value, new_password:$("#np").value}});
    csrf = r.csrf; $("#op").value = $("#np").value = ""; toast("Пароль изменён");
  });
}

// ================= ЖУРНАЛ =================
async function audit() {
  const ok = fresh();
  const rows = await api("/audit");
  if (!ok()) return;
  view.innerHTML = `<div class="page-head"><h2>Журнал действий</h2></div><div class="card" style="overflow-x:auto"><table><thead><tr><th>Когда</th><th>Кто</th><th>Действие</th><th>Подробности</th></tr></thead>
    <tbody>${rows.map((a) => `<tr><td class="small">${dt(a.at)}</td><td>${esc(a.actor)}</td><td>${esc(ACTIONS[a.action] || a.action)}${a.entity_id ? ` <span class="muted">#${esc(a.entity_id)}</span>` : ""}</td><td class="mono">${esc(a.details ? JSON.stringify(a.details) : "")}</td></tr>`).join("")}</tbody></table></div>`;
}

// ================= КОПИИ (+ проверка целостности и готовность к запуску) =================
async function backup() {
  const ok = fresh();
  const [ch, pf] = await Promise.all([api("/integrity"), api("/preflight")]);
  if (!ok()) return;
  const icon = (c) => c.ok ? "✅" : (c.critical ? "⛔" : "⚠️");
  view.innerHTML = `<div class="page-head"><h2>Резервные копии</h2></div><div class="two"><div class="list">
    <div class="card"><h3>Скачать копию</h3><p class="muted small">Все товары (с фото), заказы, платежи, покупатели и настройки. Пароль владельца в копию не попадает.</p>
      <div class="actions"><button class="btn" id="bk">Скачать резервную копию</button></div></div>
    <div class="card"><h3>Восстановить из копии</h3><p class="muted small">Текущие данные будут заменены. Перед заменой сервер сам сохранит страховочную копию.</p>
      <input type="file" id="bf" accept="application/json,.json" style="margin-top:10px">
      <div class="actions"><button class="btn danger" id="br">Восстановить</button></div></div>
    <div class="card"><h3>Проверка целостности</h3>
      <p>${ch.ok ? "✅ Проблем не найдено" : "⚠️ Найдено проблем: " + ch.problems.length} · заказов проверено: ${ch.orders_checked}</p>
      ${ch.payments_need_review ? `<p>Платежей на проверке: ${ch.payments_need_review}</p>` : ""}
      ${ch.problems.length ? `<table>${ch.problems.map((p) => `<tr><td>${p.order ? "№" + esc(p.order) : "—"}</td><td>${esc(p.issue)}</td></tr>`).join("")}</table>` : ""}</div></div>
    <div class="card"><h3>${pf.ready ? "✅ Магазин готов к запуску" : "⛔ Не готов: " + esc(pf.blockers.join(", "))}</h3>
      ${pf.warnings.length ? `<p class="muted small">Предупреждения: ${esc(pf.warnings.join(", "))}</p>` : ""}
      ${pf.checks.map((c) => `<div class="okline"><span>${icon(c)}</span><div><b>${esc(c.key)}</b><div class="muted small">${esc(c.message)}</div></div></div>`).join("")}
      <p class="muted small" style="margin-top:10px">Секреты задаются в Render → Environment, после изменения перезапустите сервис.</p></div></div>`;
  bind($("#bk"), async () => {
    const r = await fetch("/admin/api/backup", {credentials:"same-origin"});
    if (!r.ok) throw new Error("Ошибка " + r.status);
    const name = (r.headers.get("Content-Disposition") || "").match(/filename="(.+)"/)?.[1] || "chapashop_backup.json";
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement("a"); a.href = url; a.download = name; document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 8000); toast("Копия скачана");
  });
  bind($("#br"), async () => {
    const f = $("#bf").files[0]; if (!f) throw new Error("Выберите файл копии");
    if (!(await ask({title: "Заменить все данные?", text: "Магазин будет восстановлен из файла копии.", ok: "Восстановить", danger: true}))) return;
    const r = await fetch("/admin/api/restore", {method:"POST", credentials:"same-origin",
      headers:{"Content-Type":"application/json", "X-CSRF-Token":csrf, "X-Confirm-Restore":"YES"}, body: await f.text()});
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || "Ошибка " + r.status);
    toast("Восстановлено"); await backup();
  });
}

// ---------- Старт: проверяем, есть ли действующая сессия ----------
api("/me").then((d) => { csrf = d.csrf; showApp(); }).catch(showLogin);
})();
