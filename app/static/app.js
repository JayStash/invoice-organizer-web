const panels = [...document.querySelectorAll("[data-panel]")];
const steps = [...document.querySelectorAll("[data-step]")];
const fileInput = document.querySelector("#file-input");
const dropZone = document.querySelector("#drop-zone");
const selection = document.querySelector("#selection");
const selectionCount = document.querySelector("#selection-count");
const fileList = document.querySelector("#file-list");
const clearFilesButton = document.querySelector("#clear-files");
const scanButton = document.querySelector("#scan-button");
const backButton = document.querySelector("#back-button");
const confirmButton = document.querySelector("#confirm-button");
const newBatchButton = document.querySelector("#new-batch-button");
const previewBody = document.querySelector("#preview-body");
const previewSummary = document.querySelector("#preview-summary");
const uploadError = document.querySelector("#upload-error");
const previewError = document.querySelector("#preview-error");
const liveStatus = document.querySelector("#live-status");
const usageGuideButton = document.querySelector("#usage-guide-button");
const usageModal = document.querySelector("#usage-modal");
const usageCloseIcon = document.querySelector("#usage-close-icon");
const usageCloseButton = document.querySelector("#usage-close-button");
const updateModal = document.querySelector("#update-modal");
const updateTitle = document.querySelector("#update-title");
const updateNotes = document.querySelector("#update-notes");
const updateError = document.querySelector("#update-error");
const updateStatus = document.querySelector("#update-status");
const updateLaterButton = document.querySelector("#update-later-button");
const updateNowButton = document.querySelector("#update-now-button");

let selectedFiles = [];
let activeBatchId = null;
let pendingUpdate = null;

const appVersion = document.body.dataset.appVersion || "1.0.1";
const instructionsSeenKey = `invoice-organizer.instructions-seen.v${appVersion}`;

function openModal(modal) {
  modal.hidden = false;
  document.body.classList.add("has-modal");
}

function closeModal(modal) {
  modal.hidden = true;
  if (usageModal.hidden && updateModal.hidden) {
    document.body.classList.remove("has-modal");
  }
}

function instructionsHaveBeenSeen() {
  try {
    return window.localStorage.getItem(instructionsSeenKey) === "true";
  } catch (_error) {
    return false;
  }
}

function markInstructionsSeen() {
  try {
    window.localStorage.setItem(instructionsSeenKey, "true");
  } catch (_error) {
    // The guide remains available even when storage is unavailable.
  }
}

function showPendingUpdate() {
  if (!pendingUpdate || !usageModal.hidden) return;
  updateTitle.textContent = `发现新版本 v${pendingUpdate.version}`;
  updateNotes.textContent = pendingUpdate.notes || "暂无更新说明。";
  updateError.hidden = true;
  updateError.textContent = "";
  updateStatus.textContent = "";
  updateNowButton.disabled = false;
  updateLaterButton.disabled = false;
  updateNowButton.textContent = "立即更新";
  openModal(updateModal);
}

function closeUsageGuide() {
  markInstructionsSeen();
  closeModal(usageModal);
  showPendingUpdate();
}

function showUpdate(update) {
  if (!update || typeof update.version !== "string" || typeof update.notes !== "string") {
    return;
  }
  pendingUpdate = update;
  showPendingUpdate();
}

window.invoiceOrganizer = { showUpdate };

function setState(state) {
  const order = ["upload", "preview", "complete"];
  const activeIndex = order.indexOf(state);
  panels.forEach((panel) => {
    const active = panel.dataset.panel === state;
    panel.hidden = !active;
    panel.classList.toggle("is-active", active);
  });
  steps.forEach((step) => {
    const index = order.indexOf(step.dataset.step);
    step.classList.toggle("is-active", index === activeIndex);
    step.classList.toggle("is-done", index < activeIndex);
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setBusy(button, busy, busyText, idleText) {
  document.body.classList.toggle("is-busy", busy);
  button.disabled = busy;
  button.textContent = busy ? busyText : idleText;
  liveStatus.textContent = busy ? busyText : "";
}

function showError(element, message) {
  element.textContent = message;
  element.hidden = !message;
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function renderFiles() {
  fileList.replaceChildren();
  selectedFiles.forEach((file, index) => {
    const item = document.createElement("li");
    const name = document.createElement("span");
    name.className = "file-name";
    name.textContent = file.name;
    name.title = file.name;

    const size = document.createElement("span");
    size.className = "file-size";
    size.textContent = formatBytes(file.size);

    const remove = document.createElement("button");
    remove.className = "remove-file";
    remove.type = "button";
    remove.title = `移除 ${file.name}`;
    remove.setAttribute("aria-label", `移除 ${file.name}`);
    remove.textContent = "×";
    remove.addEventListener("click", () => {
      selectedFiles.splice(index, 1);
      renderFiles();
    });

    item.append(name, size, remove);
    fileList.append(item);
  });
  selection.hidden = selectedFiles.length === 0;
  selectionCount.textContent = `已选择 ${selectedFiles.length} 个文件`;
  scanButton.disabled = selectedFiles.length === 0;
}

function addFiles(files) {
  const known = new Set(selectedFiles.map((file) => file.name.toLocaleLowerCase()));
  for (const file of files) {
    const suffix = file.name.split(".").pop()?.toLocaleLowerCase();
    if (!suffix || !["pdf", "zip"].includes(suffix)) {
      showError(uploadError, `仅支持 PDF 或 ZIP：${file.name}`);
      continue;
    }
    const key = file.name.toLocaleLowerCase();
    if (!known.has(key)) {
      selectedFiles.push(file);
      known.add(key);
    }
  }
  renderFiles();
}

async function responseJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || "请求失败，请重试。");
  }
  return payload;
}

function renderPreview(data) {
  previewBody.replaceChildren();
  if (data.records.length === 0) {
    const row = document.createElement("tr");
    row.className = "empty-row";
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.textContent = "没有可显示的识别记录";
    row.append(cell);
    previewBody.append(row);
  } else {
    const keys = [
      "new_name",
      "invoice_number",
      "expense_type",
      "document_type",
      "total_amount",
      "invoice_date",
    ];
    for (const record of data.records) {
      const row = document.createElement("tr");
      keys.forEach((key) => {
        const cell = document.createElement("td");
        cell.textContent = record[key] || "";
        if (key === "total_amount") cell.className = "amount-cell";
        row.append(cell);
      });
      previewBody.append(row);
    }
  }
  const review = data.review_count ? `，${data.review_count} 项需人工复核` : "";
  previewSummary.innerHTML = `<strong>${data.planned_count}</strong> 个拟输出票据${review}`;
  confirmButton.disabled = !data.can_organize;
  showError(
    previewError,
    data.can_organize ? "" : "当前批次没有可整理票据，请重新选择文件。",
  );
}

fileInput.addEventListener("change", () => {
  showError(uploadError, "");
  addFiles(fileInput.files);
  fileInput.value = "";
});

["dragenter", "dragover"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("is-dragging");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("is-dragging");
  });
});

dropZone.addEventListener("drop", (event) => {
  showError(uploadError, "");
  addFiles(event.dataTransfer.files);
});

clearFilesButton.addEventListener("click", () => {
  selectedFiles = [];
  renderFiles();
  showError(uploadError, "");
});

scanButton.addEventListener("click", async () => {
  showError(uploadError, "");
  const form = new FormData();
  selectedFiles.forEach((file) => form.append("files", file, file.name));
  setBusy(scanButton, true, "正在识别…", "开始识别");
  try {
    const response = await fetch("/api/scan", { method: "POST", body: form });
    const data = await responseJson(response);
    activeBatchId = data.batch_id;
    renderPreview(data);
    setState("preview");
  } catch (error) {
    showError(uploadError, error.message);
  } finally {
    setBusy(scanButton, false, "正在识别…", "开始识别");
    scanButton.disabled = selectedFiles.length === 0;
  }
});

backButton.addEventListener("click", () => {
  showError(previewError, "");
  setState("upload");
});

confirmButton.addEventListener("click", async () => {
  showError(previewError, "");
  setBusy(confirmButton, true, "正在整理…", "确认整理");
  try {
    const response = await fetch("/api/organize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ batch_id: activeBatchId }),
    });
    const data = await responseJson(response);
    document.querySelector("#result-count").textContent = `${data.processed_count} 个`;
    document.querySelector("#result-total").textContent = data.grand_total
      ? `¥${data.grand_total}`
      : "空白";
    document.querySelector("#result-size").textContent = formatBytes(data.archive_size);
    document.querySelector("#download-button").href = data.download_url;
    setState("complete");
  } catch (error) {
    showError(previewError, error.message);
  } finally {
    setBusy(confirmButton, false, "正在整理…", "确认整理");
  }
});

newBatchButton.addEventListener("click", () => {
  selectedFiles = [];
  activeBatchId = null;
  renderFiles();
  showError(uploadError, "");
  showError(previewError, "");
  setState("upload");
});

usageGuideButton.addEventListener("click", () => openModal(usageModal));
usageCloseIcon.addEventListener("click", closeUsageGuide);
usageCloseButton.addEventListener("click", closeUsageGuide);

usageModal.addEventListener("click", (event) => {
  if (event.target === usageModal) closeUsageGuide();
});

updateLaterButton.addEventListener("click", () => {
  closeModal(updateModal);
});

updateNowButton.addEventListener("click", async () => {
  updateError.hidden = true;
  updateError.textContent = "";
  updateStatus.textContent = "正在下载安装包并校验…";
  updateNowButton.disabled = true;
  updateLaterButton.disabled = true;
  updateNowButton.textContent = "正在更新…";
  try {
    const api = window.pywebview?.api;
    if (!api?.install_update) {
      throw new Error("当前环境无法启动更新，请重新打开桌面应用后重试。");
    }
    const result = await api.install_update();
    if (!result?.ok) {
      throw new Error(result?.message || "更新下载失败，请稍后重试。");
    }
    updateStatus.textContent = "校验完成，正在关闭软件并启动安装程序…";
  } catch (error) {
    updateStatus.textContent = "";
    updateError.textContent = error.message || "更新下载失败，请稍后重试。";
    updateError.hidden = false;
    updateNowButton.disabled = false;
    updateLaterButton.disabled = false;
    updateNowButton.textContent = "立即更新";
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!updateModal.hidden && !updateNowButton.disabled) {
    closeModal(updateModal);
  } else if (!usageModal.hidden) {
    closeUsageGuide();
  }
});

if (!instructionsHaveBeenSeen()) {
  openModal(usageModal);
}
