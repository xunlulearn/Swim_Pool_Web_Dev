(() => {
    const launcher = document.getElementById("chatbot-launcher");
    const panel = document.getElementById("chatbot-panel");
    const closeBtn = document.getElementById("chatbot-close");
    const backdrop = document.getElementById("chatbot-backdrop");
    const thread = document.getElementById("chatbot-thread");
    const input = document.getElementById("chatbot-input");
    const sendBtn = document.getElementById("chatbot-send");
    const statusEl = document.getElementById("chatbot-status");
    const loginLink = document.getElementById("chatbot-login-link");

    const hint = document.getElementById("chatbot-hint");
    const hintDismissBtn = document.getElementById("chatbot-hint-dismiss");
    const hintNeverCheckbox = document.getElementById("chatbot-hint-never");

    if (!launcher || !panel || !closeBtn || !backdrop || !thread || !statusEl) {
        return;
    }

    const isAuthenticated = panel.dataset.authenticated === "true";
    const userKey = (panel.dataset.userKey || (isAuthenticated ? "user" : "guest")).trim();
    const hintStorageKey = `chatbot_hint_hidden_${userKey || "guest"}`;
    let hintDismissedForSession = false;

    const getCsrfToken = () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return (meta?.getAttribute("content") || "").trim();
    };

    const getHintHiddenPreference = () => {
        try {
            return window.localStorage.getItem(hintStorageKey) === "1";
        } catch (_error) {
            return false;
        }
    };

    const saveHintHiddenPreference = () => {
        try {
            window.localStorage.setItem(hintStorageKey, "1");
        } catch (_error) {
            // Ignore storage failures (private mode / blocked storage).
        }
    };

    const hideHint = () => {
        if (!hint) {
            return;
        }
        hint.classList.add("hidden");
        hint.setAttribute("aria-hidden", "true");
    };

    const showHintIfAllowed = () => {
        if (!hint) {
            return;
        }
        if (hintDismissedForSession || getHintHiddenPreference()) {
            hideHint();
            return;
        }
        if (!panel.classList.contains("hidden")) {
            hideHint();
            return;
        }

        hint.classList.remove("hidden");
        hint.setAttribute("aria-hidden", "false");
    };

    const openPanel = () => {
        panel.classList.remove("hidden");
        backdrop.classList.remove("hidden");
        launcher.setAttribute("aria-expanded", "true");
        hideHint();

        window.setTimeout(() => {
            if (isAuthenticated && input) {
                input.focus();
                return;
            }
            if (loginLink) {
                loginLink.focus();
            }
        }, 80);
    };

    const closePanel = () => {
        panel.classList.add("hidden");
        backdrop.classList.add("hidden");
        launcher.setAttribute("aria-expanded", "false");
        launcher.focus();
        window.setTimeout(showHintIfAllowed, 120);
    };

    const setStarVisualState = (starButtons, selectedRating) => {
        starButtons.forEach((button) => {
            const value = Number(button.dataset.rating || "0");
            const isSelected = selectedRating > 0 && value <= selectedRating;
            button.classList.toggle("text-amber-500", isSelected);
            button.classList.toggle("text-slate-300", !isSelected);
        });
    };

    const submitFeedback = async ({ conversationId, rating, starButtons, helperText }) => {
        const csrfToken = getCsrfToken();
        if (!csrfToken) {
            helperText.textContent = "Missing CSRF token. Please refresh the page.";
            return;
        }

        starButtons.forEach((button) => {
            button.disabled = true;
        });
        helperText.textContent = "Submitting rating...";

        try {
            const response = await fetch("/api/chat/feedback", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken,
                },
                body: JSON.stringify({
                    conversation_id: conversationId,
                    rating,
                }),
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data?.error || `Request failed (${response.status})`);
            }

            setStarVisualState(starButtons, rating);
            helperText.className = "mt-1 text-[11px] text-green-700";
            helperText.textContent = "Thanks! Your rating has been saved.";
        } catch (error) {
            helperText.className = "mt-1 text-[11px] text-red-600";
            helperText.textContent = error?.message || "Unable to submit rating. Please try again.";
            starButtons.forEach((button) => {
                button.disabled = false;
            });
        }
    };

    const appendFeedbackWidget = ({ bubble, conversationId, promptText }) => {
        if (!conversationId) {
            return;
        }

        const feedbackWrap = document.createElement("div");
        feedbackWrap.className = "mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2";

        const title = document.createElement("p");
        title.className = "text-xs font-semibold text-amber-900";
        title.textContent = promptText || "Please rate this answer (1-5 stars).";
        feedbackWrap.appendChild(title);

        const starsWrap = document.createElement("div");
        starsWrap.className = "mt-1 flex items-center gap-1";
        const starButtons = [];

        for (let value = 1; value <= 5; value += 1) {
            const starBtn = document.createElement("button");
            starBtn.type = "button";
            starBtn.dataset.rating = String(value);
            starBtn.setAttribute("aria-label", `Rate ${value} star${value > 1 ? "s" : ""}`);
            starBtn.className =
                "inline-flex h-11 w-11 items-center justify-center rounded-lg text-2xl text-slate-300 transition hover:text-amber-400 focus:outline-none focus:ring-2 focus:ring-amber-300 disabled:cursor-not-allowed disabled:opacity-70";
            starBtn.innerHTML = "&#9733;";
            starsWrap.appendChild(starBtn);
            starButtons.push(starBtn);
        }

        const helperText = document.createElement("p");
        helperText.className = "mt-1 text-[11px] text-amber-700";
        helperText.textContent = "Tap one star to submit.";

        starButtons.forEach((starBtn) => {
            starBtn.addEventListener("click", () => {
                const rating = Number(starBtn.dataset.rating || "0");
                if (!rating) {
                    return;
                }
                setStarVisualState(starButtons, rating);
                submitFeedback({
                    conversationId,
                    rating,
                    starButtons,
                    helperText,
                });
            });
        });

        feedbackWrap.appendChild(starsWrap);
        feedbackWrap.appendChild(helperText);
        bubble.appendChild(feedbackWrap);
    };

    const appendMessage = ({ role, text, sources = [], feedback = null }) => {
        const wrapper = document.createElement("div");
        wrapper.className = role === "user" ? "flex justify-end" : "flex justify-start";

        const bubble = document.createElement("div");
        bubble.className =
            role === "user"
                ? "max-w-[88%] rounded-2xl rounded-br-sm bg-ntu-blue px-3 py-2 text-sm text-white shadow-sm"
                : "max-w-[88%] rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm";

        const textNode = document.createElement("p");
        textNode.className = "whitespace-pre-wrap break-words leading-relaxed";
        textNode.textContent = text;
        bubble.appendChild(textNode);

        if (role === "assistant" && Array.isArray(sources) && sources.length > 0) {
            const sourceWrap = document.createElement("div");
            sourceWrap.className = "mt-2 border-t border-slate-200 pt-2";

            const sourceTitle = document.createElement("p");
            sourceTitle.className = "mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400";
            sourceTitle.textContent = "Sources";
            sourceWrap.appendChild(sourceTitle);

            const list = document.createElement("ul");
            list.className = "space-y-1";

            sources.forEach((source) => {
                if (typeof source !== "string" || !source.trim()) {
                    return;
                }
                const li = document.createElement("li");
                const link = document.createElement("a");
                link.href = source;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.textContent = source;
                link.className = "break-all text-xs text-ntu-blue underline-offset-2 hover:underline";
                li.appendChild(link);
                list.appendChild(li);
            });

            if (list.children.length > 0) {
                sourceWrap.appendChild(list);
                bubble.appendChild(sourceWrap);
            }
        }

        if (role === "assistant" && feedback && feedback.required) {
            appendFeedbackWidget({
                bubble,
                conversationId: feedback.conversationId,
                promptText: feedback.prompt,
            });
        }

        wrapper.appendChild(bubble);
        thread.appendChild(wrapper);
        thread.scrollTop = thread.scrollHeight;
    };

    const setLoading = (isLoading) => {
        if (!sendBtn || !input) {
            return;
        }
        sendBtn.disabled = isLoading;
        input.disabled = isLoading;
        sendBtn.textContent = isLoading ? "Sending..." : "Send";
        statusEl.textContent = isLoading ? "Assistant is thinking..." : "";
    };

    const ask = async () => {
        if (!isAuthenticated) {
            statusEl.textContent = "Please log in to chat with NTU Pool Assistant.";
            return;
        }
        if (!input || !sendBtn) {
            statusEl.textContent = "Chat composer is unavailable.";
            return;
        }

        const message = input.value.trim();
        if (!message) {
            statusEl.textContent = "Please enter a question.";
            return;
        }

        const csrfToken = getCsrfToken();
        if (!csrfToken) {
            statusEl.textContent = "Missing CSRF token. Please refresh the page.";
            return;
        }

        openPanel();
        appendMessage({ role: "user", text: message });
        input.value = "";
        setLoading(true);

        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken,
                },
                body: JSON.stringify({ message }),
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                const errorMsg = data?.error || `Request failed (${response.status})`;
                appendMessage({ role: "assistant", text: errorMsg });
                statusEl.textContent = "";
                return;
            }

            const reply = typeof data?.reply === "string" ? data.reply.trim() : "";
            const feedbackRequired = Boolean(data?.feedback_required);
            const conversationId =
                typeof data?.conversation_id === "string" ? data.conversation_id : "";
            const feedbackPrompt =
                typeof data?.feedback_prompt === "string" ? data.feedback_prompt : "";

            appendMessage({
                role: "assistant",
                text: reply || "No reply returned.",
                sources: data?.sources || [],
                feedback: feedbackRequired
                    ? {
                          required: true,
                          conversationId,
                          prompt: feedbackPrompt,
                      }
                    : null,
            });
            statusEl.textContent = "Done.";
        } catch (_error) {
            appendMessage({ role: "assistant", text: "Request failed. Please try again." });
            statusEl.textContent = "";
        } finally {
            setLoading(false);
            if (input) {
                input.focus();
            }
        }
    };

    launcher.addEventListener("click", () => {
        if (panel.classList.contains("hidden")) {
            openPanel();
            if (!isAuthenticated) {
                statusEl.textContent = "Please log in to chat with NTU Pool Assistant.";
            }
        } else {
            closePanel();
        }
    });

    closeBtn.addEventListener("click", closePanel);
    backdrop.addEventListener("click", closePanel);

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !panel.classList.contains("hidden")) {
            closePanel();
        }
    });

    if (sendBtn) {
        sendBtn.addEventListener("click", ask);
    }

    if (input) {
        input.addEventListener("keydown", (event) => {
            if (event.key !== "Enter") {
                return;
            }
            if (event.isComposing) {
                return;
            }
            // Ctrl/Cmd + Enter keeps native newline behavior.
            if (event.ctrlKey || event.metaKey) {
                return;
            }
            // Enter sends message.
            event.preventDefault();
            ask();
        });
    }

    if (hintDismissBtn) {
        hintDismissBtn.addEventListener("click", () => {
            hintDismissedForSession = true;
            hideHint();
        });
    }

    if (hintNeverCheckbox) {
        if (getHintHiddenPreference()) {
            hintNeverCheckbox.checked = true;
        }

        hintNeverCheckbox.addEventListener("change", () => {
            if (!hintNeverCheckbox.checked) {
                return;
            }
            saveHintHiddenPreference();
            hintDismissedForSession = true;
            hideHint();
        });
    }

    window.setTimeout(showHintIfAllowed, 700);
})();
