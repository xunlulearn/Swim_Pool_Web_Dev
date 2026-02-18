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

    const escapeHtml = (text) => {
        const raw = String(text ?? "");
        return raw
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    };

    const renderAssistantMarkdown = (text) => {
        let html = escapeHtml(text);

        html = html.replace(
            /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
            '<a href="$2" target="_blank" rel="noopener noreferrer" class="text-ntu-blue underline underline-offset-2">$1</a>'
        );
        html = html.replace(
            /`([^`\n]+)`/g,
            '<code class="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.9em] text-slate-800">$1</code>'
        );
        html = html.replace(/\*\*([^*\n][^*\n]*?)\*\*/g, "<strong>$1</strong>");
        html = html.replace(/\*\*/g, "");

        const blocks = html
            .split(/\n{2,}/)
            .map((block) => block.trim())
            .filter(Boolean)
            .map((block) => `<p class="mb-2 last:mb-0">${block.replace(/\n/g, "<br>")}</p>`);

        if (blocks.length === 0) {
            return "<p></p>";
        }
        return blocks.join("");
    };

    const setStarVisualState = (starButtons, selectedRating) => {
        starButtons.forEach((button) => {
            const value = Number(button.dataset.rating || "0");
            const isSelected = selectedRating > 0 && value <= selectedRating;
            button.classList.toggle("text-amber-500", isSelected);
            button.classList.toggle("text-slate-300", !isSelected);
        });
    };

    const submitFeedback = async ({
        conversationId,
        rating,
        comment,
        starButtons,
        helperText,
        commentInput,
    }) => {
        const csrfToken = getCsrfToken();
        if (!csrfToken) {
            helperText.textContent = "Missing CSRF token. Please refresh the page.";
            return;
        }

        starButtons.forEach((button) => {
            button.disabled = true;
        });
        if (commentInput) {
            commentInput.disabled = true;
        }
        helperText.textContent = "\u6b63\u5728\u63d0\u4ea4\u8bc4\u5206...";

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
                    comment,
                }),
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data?.error || `Request failed (${response.status})`);
            }

            setStarVisualState(starButtons, rating);
            helperText.className = "mt-1 text-[11px] text-green-700";
            helperText.textContent =
                "\u611f\u8c22\u53cd\u9988\uff01\u795d\u60a8\u5728NTU\u7684\u6cf3\u6c60\u73a9\u5f97\u5f00\u5fc3\u3002";
        } catch (error) {
            helperText.className = "mt-1 text-[11px] text-red-600";
            helperText.textContent = error?.message || "Unable to submit rating. Please try again.";
            starButtons.forEach((button) => {
                button.disabled = false;
            });
            if (commentInput) {
                commentInput.disabled = false;
            }
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
        title.textContent =
            promptText ||
            "\u8bf7\u60a8\u5bf9\u6211\u8fdb\u884c\u6ee1\u610f\u5ea6\u8bc4\u5206\uff0c\u5e2e\u52a9\u6211\u4ee5\u540e\u53d8\u5f97\u66f4\u52a0\u806a\u660e\u3002";
        feedbackWrap.appendChild(title);

        const commentInput = document.createElement("textarea");
        commentInput.rows = 2;
        commentInput.maxLength = 500;
        commentInput.placeholder = "\u6b22\u8fce\u8f93\u5165\u53cd\u9988\u610f\u89c1\uff08\u9009\u586b\uff09";
        commentInput.className =
            "mt-2 w-full resize-none rounded-lg border border-amber-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:outline-none focus:ring-2 focus:ring-amber-300";
        feedbackWrap.appendChild(commentInput);

        const starsWrap = document.createElement("div");
        starsWrap.className = "mt-2 flex items-center gap-1";
        const starButtons = [];
        let selectedRating = 0;

        for (let value = 1; value <= 5; value += 1) {
            const starBtn = document.createElement("button");
            starBtn.type = "button";
            starBtn.dataset.rating = String(value);
            starBtn.setAttribute("aria-label", `Rate ${value} star${value > 1 ? "s" : ""}`);
            starBtn.className =
                "inline-flex h-11 w-11 items-center justify-center rounded-lg text-2xl text-slate-300 transition focus:outline-none focus:ring-2 focus:ring-amber-300 disabled:cursor-not-allowed disabled:opacity-70";
            starBtn.innerHTML = "&#9733;";
            starsWrap.appendChild(starBtn);
            starButtons.push(starBtn);
        }

        const helperText = document.createElement("p");
        helperText.className = "mt-1 text-[11px] text-amber-700";
        helperText.textContent = "\u70b9\u51fb\u661f\u661f\u5373\u53ef\u63d0\u4ea4\u8bc4\u5206\u3002";

        const restoreSelectedVisualState = () => {
            setStarVisualState(starButtons, selectedRating);
        };

        starsWrap.addEventListener("mouseleave", restoreSelectedVisualState);

        starButtons.forEach((starBtn) => {
            starBtn.addEventListener("mouseenter", () => {
                const hovered = Number(starBtn.dataset.rating || "0");
                setStarVisualState(starButtons, hovered);
            });

            starBtn.addEventListener("focus", () => {
                const focused = Number(starBtn.dataset.rating || "0");
                setStarVisualState(starButtons, focused);
            });

            starBtn.addEventListener("click", () => {
                const rating = Number(starBtn.dataset.rating || "0");
                if (!rating) {
                    return;
                }
                selectedRating = rating;
                setStarVisualState(starButtons, selectedRating);
                submitFeedback({
                    conversationId,
                    rating,
                    comment: commentInput.value.trim(),
                    starButtons,
                    helperText,
                    commentInput,
                });
            });
        });

        feedbackWrap.appendChild(starsWrap);
        feedbackWrap.appendChild(helperText);
        bubble.appendChild(feedbackWrap);
    };

    const appendQuickQuestions = ({ bubble, quickQuestions }) => {
        if (!Array.isArray(quickQuestions) || quickQuestions.length === 0) {
            return;
        }

        const wrap = document.createElement("div");
        wrap.className = "mt-3 border-t border-slate-200/80 pt-2.5";

        const title = document.createElement("p");
        title.className = "mb-2 text-[11px] font-semibold text-slate-500";
        title.textContent = "\u4f60\u53ef\u4ee5\u7ee7\u7eed\u95ee\uff1a";
        wrap.appendChild(title);

        const list = document.createElement("div");
        list.className = "flex flex-wrap gap-2";

        quickQuestions.forEach((question) => {
            if (typeof question !== "string") {
                return;
            }
            const text = question.trim();
            if (!text) {
                return;
            }

            const btn = document.createElement("button");
            btn.type = "button";
            btn.className =
                "inline-flex min-h-[36px] max-w-full items-center rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-left text-xs text-slate-700 shadow-sm transition-all duration-200 hover:border-ntu-blue/40 hover:bg-white hover:text-ntu-blue focus:outline-none focus:ring-2 focus:ring-ntu-blue/30";
            btn.textContent = text;
            btn.addEventListener("click", () => {
                if (!isAuthenticated || !input || !sendBtn || sendBtn.disabled) {
                    return;
                }
                input.value = text;
                ask();
            });
            list.appendChild(btn);
        });

        if (list.childElementCount > 0) {
            wrap.appendChild(list);
            bubble.appendChild(wrap);
        }
    };

    const appendMessage = ({ role, text, feedback = null, quickQuestions = [] }) => {
        const isUser = role === "user";

        const wrapper = document.createElement("div");
        wrapper.className = isUser ? "flex justify-end" : "flex justify-start";

        const bubble = document.createElement("div");
        bubble.className = isUser
            ? "max-w-[84%] rounded-2xl rounded-br-md border border-blue-800/70 bg-gradient-to-br from-ntu-blue to-blue-800 px-3.5 py-2.5 text-sm text-white shadow-[0_10px_22px_-14px_rgba(30,64,175,0.8)]"
            : "max-w-[90%] rounded-2xl rounded-bl-md border border-slate-200 bg-gradient-to-b from-white to-slate-50 px-3.5 py-2.5 text-sm text-slate-700 shadow-[0_12px_24px_-16px_rgba(15,23,42,0.45)]";

        const textNode = document.createElement("div");
        textNode.className = "break-words leading-relaxed";
        if (!isUser) {
            textNode.innerHTML = renderAssistantMarkdown(text);
        } else {
            textNode.classList.add("whitespace-pre-wrap");
            textNode.textContent = text;
        }
        bubble.appendChild(textNode);

        if (!isUser && feedback && feedback.required) {
            appendFeedbackWidget({
                bubble,
                conversationId: feedback.conversationId,
                promptText: feedback.prompt,
            });
        }

        if (!isUser) {
            appendQuickQuestions({
                bubble,
                quickQuestions,
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
            const conversationId = typeof data?.conversation_id === "string" ? data.conversation_id : "";
            const feedbackPrompt = typeof data?.feedback_prompt === "string" ? data.feedback_prompt : "";
            const quickQuestions = Array.isArray(data?.quick_questions) ? data.quick_questions : [];

            appendMessage({
                role: "assistant",
                text: reply || "No reply returned.",
                feedback: feedbackRequired
                    ? {
                          required: true,
                          conversationId,
                          prompt: feedbackPrompt,
                      }
                    : null,
                quickQuestions,
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
            if (event.ctrlKey || event.metaKey) {
                return;
            }
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
