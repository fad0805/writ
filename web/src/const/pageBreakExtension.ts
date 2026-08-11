import { Extension } from "@tiptap/core";
import { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { Plugin, PluginKey } from "prosemirror-state";
import { DecorationSet, Decoration } from "prosemirror-view";

const LINES_PER_PAGE = 20;

const pageBreakPluginKey = new PluginKey("pageBreaks");

function findBlockNodes(doc: ProseMirrorNode): number[] {
  const positions: number[] = [];
  doc.forEach((node: ProseMirrorNode, offset: number) => {
    if (node.isBlock) {
      positions.push(offset);
    }
  });
  return positions;
}

function buildDecorations(doc: ProseMirrorNode, enabled: boolean): DecorationSet {
  if (!enabled) return DecorationSet.empty;
  const blockPositions = findBlockNodes(doc);
  const decorations: Decoration[] = [];
  for (let i = LINES_PER_PAGE - 1; i < blockPositions.length; i += LINES_PER_PAGE) {
    const pos = blockPositions[i] + doc.child(i).nodeSize;
    const pageNum = Math.floor((i + 1) / LINES_PER_PAGE);
    decorations.push(
      Decoration.widget(pos, () => {
        const el = document.createElement("div");
        el.className = "page-break-marker";
        el.setAttribute("contenteditable", "false");
        const inner = document.createElement("div");
        inner.className = "page-break-line";
        const label = document.createElement("span");
        label.className = "page-break-label";
        label.textContent = `— ${pageNum}페이지 끝 —`;
        inner.appendChild(label);
        el.appendChild(inner);
        return el;
      }, { side: 1 })
    );
  }
  return DecorationSet.create(doc, decorations);
}

export const PageBreakExtension = Extension.create({
  name: "pageBreaks",

  addOptions() {
    return { enabled: false };
  },

  addStorage() {
    return { enabled: false };
  },

  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: pageBreakPluginKey,
        state: {
          init: (_tr, state) => {
            return buildDecorations(state.doc, this.storage.enabled);
          },
          apply: (tr, old, oldState, newState) => {
            if (this.storage.enabled && (tr.docChanged || tr.getMeta("pageBreaksToggle"))) {
              return buildDecorations(newState.doc, this.storage.enabled);
            }
            if (!this.storage.enabled) return DecorationSet.empty;
            return old.map(tr.mapping, tr.doc);
          },
        },
        props: {
          decorations(state) {
            return this.getState(state);
          },
        },
      }),
    ];
  },
});
