(() => {
  const config = window.SCHOLARLY_FIREBASE_CONFIG || {};
  const hasFirebase = Boolean(config.apiKey && config.projectId && window.firebase);
  let auth = null;

  if (hasFirebase) {
    if (!firebase.apps.length) firebase.initializeApp(config);
    auth = firebase.auth();
  }

  const signInButton = document.querySelector("#sign-in-button");
  const signOutButton = document.querySelector("#sign-out-button");
  const authStatus = document.querySelector("#auth-status");
  const accountMessage = document.querySelector("#account-message");

  function message(text, isError = false, target = accountMessage) {
    if (!target) return;
    target.textContent = text;
    target.classList.toggle("error-text", isError);
  }

  async function api(path, options = {}) {
    if (!auth || !auth.currentUser) throw new Error("Sign in with Google to continue.");
    const token = await auth.currentUser.getIdToken();
    const headers = { Authorization: `Bearer ${token}`, ...(options.headers || {}) };
    if (options.body) headers["Content-Type"] = "application/json";
    const response = await fetch(path, { ...options, headers });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "The request could not be completed.");
    return payload;
  }

  function make(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function articleCard(article) {
    const card = make("article", "result-card");
    const meta = make("div", "result-meta");
    meta.append(make("span", "category-pill", article.primary_category || article.categories?.[0] || "arXiv"));
    meta.append(make("span", "", article.published?.slice(0, 10) || ""));
    const heading = make("h3");
    const link = make("a", "", article.title);
    link.href = `/article/${encodeURIComponent(article.arxiv_id)}`;
    heading.append(link);
    card.append(meta, heading, make("p", "author-line", article.authors.join(", ")));
    if (article.activity_at) card.append(make("p", "subtle-note", `Last activity: ${article.activity_at}`));
    return card;
  }

  function renderArticles(container, articles, emptyText) {
    container.replaceChildren();
    if (!articles.length) {
      container.append(make("div", "empty-state", ""));
      const empty = container.firstElementChild;
      empty.append(make("span", "", "▤"), make("h2", "", "Nothing here yet"), make("p", "", emptyText));
      return;
    }
    articles.forEach((article) => container.append(articleCard(article)));
  }

  async function loadAccount() {
    const container = document.querySelector("#account-content");
    const mode = container?.dataset.mode;
    if (!container || !auth?.currentUser) return;
    try {
      container.replaceChildren(make("p", "subtle-note", "Loading…"));
      if (mode === "trackers") {
        const { trackers } = await api("/api/trackers");
        container.replaceChildren();
        if (!trackers.length) {
          renderArticles(container, [], "Create your first tracker to follow a topic, author, or category.");
          return;
        }
        trackers.forEach((tracker) => {
          const card = make("section", "tracker-card");
          const head = make("div", "tracker-card-head");
          const info = make("div");
          info.append(make("h2", "", tracker.name));
          info.append(make("p", "subtle-note", [tracker.keywords, tracker.authors, tracker.categories].filter(Boolean).join(" · ")));
          head.append(info);
          const controls = make("div", "button-row");
          const refresh = make("button", "button button-outline button-small", "Refresh");
          refresh.type = "button";
          refresh.addEventListener("click", async () => {
            try {
              const result = await api(`/api/trackers/${encodeURIComponent(tracker.id)}/refresh`, { method: "POST" });
              message(`Tracker checked. ${result.matched} matching papers found.`);
              await loadAccount();
            } catch (error) { message(error.message, true); }
          });
          const remove = make("button", "button button-quiet button-small", "Delete");
          remove.type = "button";
          remove.addEventListener("click", async () => {
            try {
              await api(`/api/trackers/${encodeURIComponent(tracker.id)}`, { method: "DELETE" });
              await loadAccount();
            } catch (error) { message(error.message, true); }
          });
          controls.append(refresh, remove);
          head.append(controls);
          card.append(head);
          container.append(card);
        });
      } else if (mode === "library") {
        const library = await api("/api/library");
        const favoritesSection = make("section", "library-section");
        favoritesSection.append(make("h2", "", "Favorites"));
        const favoritesList = make("div", "article-list");
        renderArticles(favoritesList, library.favorites, "Save papers from their article pages to keep them here.");
        favoritesSection.append(favoritesList);
        const historySection = make("section", "library-section");
        historySection.append(make("h2", "", "Reading history"));
        const historyList = make("div", "article-list");
        renderArticles(historyList, library.history, "Papers you open will appear here.");
        historySection.append(historyList);
        container.replaceChildren(favoritesSection, historySection);
      } else if (mode === "alerts") {
        const { alerts } = await api("/api/alerts");
        container.replaceChildren();
        if (!alerts.length) {
          renderArticles(container, [], "Refresh a tracker to check arXiv for matching papers. New matches appear here.");
          return;
        }
        alerts.forEach((alert) => {
          const item = make("article", `alert-card${alert.read_at ? " is-read" : ""}`);
          const title = make("a", "alert-title", alert.title);
          title.href = `/article/${encodeURIComponent(alert.arxiv_id)}`;
          item.append(make("span", "category-pill", alert.tracker_name), title, make("p", "subtle-note", alert.created_at));
          if (!alert.read_at) {
            const read = make("button", "button button-quiet button-small", "Mark read");
            read.type = "button";
            read.addEventListener("click", async () => {
              try {
                await api(`/api/alerts/${alert.id}/read`, { method: "POST" });
                await loadAccount();
              } catch (error) { message(error.message, true); }
            });
            item.append(read);
          }
          container.append(item);
        });
      }
    } catch (error) {
      container.replaceChildren(make("p", "notice notice-error", error.message));
    }
  }

  async function loadComments() {
    const container = document.querySelector("#comments-list");
    if (!container) return;
    try {
      const response = await fetch(`/api/articles/${encodeURIComponent(container.dataset.articleId)}/comments`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not load comments.");
      container.replaceChildren();
      if (!data.comments.length) {
        container.append(make("p", "subtle-note", "No comments yet. Start the conversation."));
        return;
      }
      const byParent = new Map();
      data.comments.forEach((comment) => {
        const key = comment.parent_id || 0;
        if (!byParent.has(key)) byParent.set(key, []);
        byParent.get(key).push(comment);
      });
      function addThread(parentId, target, depth = 0) {
        (byParent.get(parentId) || []).forEach((comment) => {
          const card = make("article", `comment-card${depth ? " comment-reply" : ""}`);
          card.append(make("strong", "", comment.display_name || "Researcher"));
          card.append(make("span", "subtle-note", comment.created_at));
          card.append(make("p", "", comment.body));
          const reply = make("button", "button button-quiet button-small", "Reply");
          reply.type = "button";
          reply.addEventListener("click", () => {
            const existing = card.querySelector("form");
            if (existing) {
              existing.remove();
              return;
            }
            const form = document.createElement("form");
            form.className = "reply-form";
            const input = document.createElement("textarea");
            input.name = "body";
            input.rows = 2;
            input.maxLength = 5000;
            input.required = true;
            input.placeholder = "Write a reply…";
            const submit = make("button", "button button-outline button-small", "Post reply");
            submit.type = "submit";
            form.append(input, submit);
            form.addEventListener("submit", async (event) => {
              event.preventDefault();
              try {
                await api(`/api/articles/${encodeURIComponent(container.dataset.articleId)}/comments`, {
                  method: "POST",
                  body: JSON.stringify({ body: input.value, parent_id: comment.id }),
                });
                await loadComments();
              } catch (error) { message(error.message, true, document.querySelector("#comment-message")); }
            });
            card.append(form);
          });
          card.append(reply);
          const replies = make("div", "comment-children");
          card.append(replies);
          target.append(card);
          addThread(comment.id, replies, depth + 1);
        });
      }
      addThread(0, container);
    } catch (error) {
      container.replaceChildren(make("p", "notice notice-error", error.message));
    }
  }

  async function loadArticleActions() {
    const button = document.querySelector("#favorite-button");
    if (!button || !auth?.currentUser) return;
    try {
      await api(`/api/articles/${encodeURIComponent(button.dataset.articleId)}/history`, { method: "POST" });
      const library = await api("/api/library");
      const isSaved = library.favorites.some((article) => article.arxiv_id === button.dataset.articleId);
      button.textContent = isSaved ? "★ Saved" : "☆ Save paper";
      button.onclick = async () => {
        try {
          if (button.textContent.includes("Saved")) {
            await api(`/api/articles/${encodeURIComponent(button.dataset.articleId)}/favorite`, { method: "DELETE" });
            button.textContent = "☆ Save paper";
          } else {
            await api(`/api/articles/${encodeURIComponent(button.dataset.articleId)}/favorite`, { method: "POST" });
            button.textContent = "★ Saved";
          }
        } catch (error) { window.alert(error.message); }
      };
    } catch (error) { message(error.message, true); }
  }

  signInButton?.addEventListener("click", async () => {
    if (!auth) {
      message("Firebase sign-in is not configured. See the Firebase setup in README.", true, authStatus);
      return;
    }
    try { await auth.signInWithPopup(new firebase.auth.GoogleAuthProvider()); }
    catch (error) { message(error.message, true, authStatus); }
  });
  signOutButton?.addEventListener("click", () => auth?.signOut());

  if (auth) {
    auth.onAuthStateChanged(async (user) => {
      signInButton?.classList.toggle("hidden", Boolean(user));
      signOutButton?.classList.toggle("hidden", !user);
      if (authStatus) authStatus.textContent = user ? (user.displayName || user.email || "Signed in") : "Not signed in";
      if (accountMessage) message(user ? `Signed in as ${user.displayName || user.email}.` : "Sign in with Google to see your personal research space.");
      if (user) {
        try { await api("/api/me", { method: "POST" }); }
        catch (error) { message(error.message, true); }
        await loadAccount();
        await loadArticleActions();
      } else {
        const container = document.querySelector("#account-content");
        if (container) renderArticles(container, [], "Sign in with Google to manage this space.");
        const favorite = document.querySelector("#favorite-button");
        if (favorite) favorite.textContent = "☆ Sign in to save";
      }
    });
  } else {
    if (authStatus) authStatus.title = "Set Firebase variables to enable Google sign-in.";
  }

  document.querySelector("#tracker-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form).entries());
    try {
      await api("/api/trackers", { method: "POST", body: JSON.stringify(data) });
      form.reset();
      message("Tracker created.");
      await loadAccount();
    } catch (error) { message(error.message, true); }
  });

  document.querySelector("#comment-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const target = document.querySelector("#comment-message");
    try {
      await api(`/api/articles/${encodeURIComponent(form.dataset.articleId)}/comments`, {
        method: "POST",
        body: JSON.stringify({ body: new FormData(form).get("body") }),
      });
      form.reset();
      message("Comment posted.", false, target);
      await loadComments();
    } catch (error) { message(error.message, true, target); }
  });

  loadComments();
})();
