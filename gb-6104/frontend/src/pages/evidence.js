import { api } from "../api/workbench.js";
import { errorText, field } from "../components/common/fields.js";
import { empty, pageHeading, section } from "../components/common/panel.js";
import { resultTable, table } from "../components/common/table.js";
import { submit } from "../hooks/submit.js";
import { el } from "../utils/dom.js";
import { cell, download, time } from "../utils/format.js";

function reviewForm(id, saved) {
  const form = el("form", {id: "review-form"},
    field("复核意见", el("textarea", {name: "note", required: true, minlength: 3, maxlength: 500, rows: 3})),
    errorText(), el("button", {type: "submit"}, "签署复核"));
  submit(form, async values => saved(await api.submitReview(id, {note: values.get("note")})));
  return form;
}

function signature(review) {
  return el("div", {"data-testid": "reviewed", class: "signature"},
    el("strong", {}, `已签署 · ${review.actor}`), el("p", {}, review.note), el("time", {}, time(review.created_at)));
}

function skippedList(bill) {
  const skipped = bill.document?.["暂缓航次"] || [];
  if (!skipped.length) return empty("无暂缓航次。");
  return table(["暂缓航次", "原因"], skipped.map(item => [item["航次"], item["原因"] || "暂缓"]), "暂缓航次");
}

function billView(run, bill, user) {
  const issue = errorText();
  const downloadButton = el("button", {
    type: "button",
    onclick: async () => {
      downloadButton.disabled = true;
      issue.textContent = "";
      try {
        await download(await api.downloadHandover(run.id), `handover-${run.id}.json`);
      } catch (error) {
        issue.textContent = error.message;
      } finally {
        downloadButton.disabled = false;
      }
    },
  }, "下载原单（港务交接单）");

  const retryButton = user?.role === "reviewer" ? el("button", {
    type: "button",
    "aria-label": "重试交接",
    onclick: async () => {
      retryButton.disabled = true;
      issue.textContent = "";
      try {
        const sameBill = await api.submitHandover(run.id, {});
        const panel = retryButton.closest("[data-testid='handover-panel']");
        panel.replaceChildren(billView(run, sameBill, user));
      } catch (error) {
        issue.textContent = error.message;
        retryButton.disabled = false;
      }
    },
  }, "回执丢失？重试交接") : null;

  const lines = bill.document?.["调账明细"] || [];
  return el("div", {"data-testid": "handed-over", class: "signature bill-card"},
    el("div", {class: "bill-heading"},
      el("strong", {}, `已交接 · ${bill.actor}`),
      el("span", {"data-testid": "receipt-no"}, `交接回执：${bill.receipt_no || bill.bill_no}`)),
    el("p", {}, `复核日：${bill.review_date}；本次调账合计：${cell(bill.total_amount_cents ?? bill.total_cents)} 分`),
    bill.note ? el("p", {}, bill.note) : null,
    el("time", {}, time(bill.created_at)),
    section("按航次累计抵扣后的调账单", lines.length ? resultTable(lines) : empty("没有应调航次。")),
    section("本次跳过的暂缓航次", skippedList(bill)),
    el("div", {class: "actions"}, downloadButton, retryButton),
    issue);
}

function handoverPanel(run, review, user, bill) {
  const host = el("div", {"data-testid": "handover-panel", class: "stack"});
  if (bill) {
    host.append(billView(run, bill, user));
    return host;
  }

  if (!review) {
    host.append(empty("批次签署复核后，才能交接港务调账单。"));
    return host;
  }
  if (user.role !== "reviewer") {
    host.append(empty("等待业务复核员交接港务调账单。"));
    return host;
  }

  const issue = errorText();
  const button = el("button", {type: "button", "data-testid": "create-handover"}, "确认交接并生成港务调账单");
  button.addEventListener("click", async () => {
    button.disabled = true;
    issue.textContent = "";
    try {
      const created = await api.submitHandover(run.id, {});
      host.replaceChildren(billView(run, created, user));
    } catch (error) {
      issue.textContent = error.message;
      button.disabled = false;
    }
  });
  host.append(el("p", {}, "按航次扣除已交接累计金额；暂缓航次自动跳过。重复提交不会新增调账单。"),
    el("div", {class: "actions"}, button), issue);
  return host;
}

export async function evidencePage(config, user, route) {
  const runs = (await api.runs()).filter(item => item.status === "done");
  const run = route.id ? await api.run(route.id) : runs[0];
  if (!run?.result) return el("div", {class: "page"},
    pageHeading(config.modules[3], null), empty("成功执行一个批次后可以查看、签核和下载证据。"),
    el("a", {href: "#runs"}, config.modules[2]));

  const [review, handover] = await Promise.all([api.review(run.id), api.handover(run.id)]);
  const issue = errorText();
  const button = el("button", {type: "button", onclick: async () => {
    button.disabled = true;
    issue.textContent = "";
    try {
      await download(await api.export(run.id), `evidence-${run.id}.json`);
    } catch (error) {
      issue.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }}, "导出证据");
  const signing = el("div", {});
  const handoverContainer = el("div", {}, handoverPanel(run, review, user, handover));
  signing.append(review ? signature(review) : user.role === "reviewer" ?
    reviewForm(run.id, async savedReview => {
      signing.replaceChildren(signature(savedReview));
      // The handover action is only available after the signature exists.
      handoverContainer.replaceChildren(handoverPanel(run, savedReview, user, handover));
    }) : empty("待复核员签署。"));
  const options = el("select", {"aria-label": "选择已完成的批次", onchange: event => {
    location.hash = `evidence/${event.target.value}`;
  }}, runs.map(item => el("option", {value: item.id, selected: item.id === run.id}, `#${item.id} ${item.case_title}`)));
  return el("div", {class: "page evidence"},
    pageHeading(config.modules[3], run.case_title, button),
    issue, options,
    el("section", {class: "feature evidence-summary"}, el("div", {}, el("h2", {}, "批次判定"), el("p", {}, run.result.summary)),
      el("details", {}, el("summary", {}, "证据摘要"), el("code", {}, run.digest))),
    el("dl", {class: "metrics"}, Object.entries(run.result.metrics).map(([label, value]) =>
      el("div", {}, el("dt", {}, label), el("dd", {}, cell(value))))),
    section("业务结果明细", run.result.rows.length ? resultTable(run.result.rows) : empty("此批次无明细。")),
    section("复核签署", signing),
    section("港务交接", handoverContainer));
}
