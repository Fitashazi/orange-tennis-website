(function () {
  const host = document.getElementById("account-nav");
  if (!host) return;
  const light = host.dataset.tone === "light";
  const quiet = light ? "btn btn-outline-light btn-sm" : "btn btn-outline btn-sm";
  const solid = "btn btn-primary btn-sm";

  function loggedOut() {
    host.innerHTML =
      '<a href="/login" class="' + quiet + '">Giriş</a>' +
      '<a href="/kayit" class="' + solid + '">Kayıt ol</a>';
  }

  loggedOut();
  fetch("/api/me")
    .then((res) => res.json())
    .then((data) => {
      if (data.role === "staff") {
        host.innerHTML = '<a href="/admin" class="' + quiet + '">Yönetim</a>';
      } else if (data.role === "member") {
        host.innerHTML = '<a href="/hesap" class="' + quiet + '">Hesabım</a>';
      } else {
        loggedOut();
      }
    })
    .catch(() => {});
})();
