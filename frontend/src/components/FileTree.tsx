import { useState } from "react";

interface TreeFolder {
  type: "folder";
  name: string;
  children: TreeItem[];
}

interface TreeFile {
  type: "file";
  name: string;
  path: string;
}

type TreeItem = TreeFolder | TreeFile;

function buildTree(paths: string[]): TreeItem[] {
  const root: TreeItem[] = [];
  for (const path of paths) {
    const parts = path.split("/");
    let children = root;
    parts.forEach((part, i) => {
      if (i === parts.length - 1) {
        children.push({ type: "file", name: part, path });
        return;
      }
      let folder = children.find((c): c is TreeFolder => c.type === "folder" && c.name === part);
      if (!folder) {
        folder = { type: "folder", name: part, children: [] };
        children.push(folder);
      }
      children = folder.children;
    });
  }

  const sort = (items: TreeItem[]) => {
    items.sort((a, b) => (a.type === b.type ? a.name.localeCompare(b.name) : a.type === "folder" ? -1 : 1));
    items.forEach((item) => item.type === "folder" && sort(item.children));
  };
  sort(root);
  return root;
}

function FileTreeNode({
  item,
  activeFile,
  onSelect,
}: {
  item: TreeItem;
  activeFile: string | null;
  onSelect: (path: string) => void;
}) {
  const [open, setOpen] = useState(true);

  if (item.type === "file") {
    return (
      <button
        className={`file-tree-item file-tree-file${item.path === activeFile ? " active" : ""}`}
        onClick={() => onSelect(item.path)}
      >
        {item.name}
      </button>
    );
  }

  return (
    <div className="file-tree-folder">
      <button className="file-tree-item file-tree-folder-label" onClick={() => setOpen((o) => !o)}>
        {open ? "▾" : "▸"} {item.name}
      </button>
      {open && (
        <div className="file-tree-children">
          {item.children.map((child) => (
            <FileTreeNode
              key={child.type === "file" ? child.path : child.name}
              item={child}
              activeFile={activeFile}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function FileTree({
  files,
  activeFile,
  onSelect,
}: {
  files: Record<string, string>;
  activeFile: string | null;
  onSelect: (path: string) => void;
}) {
  const tree = buildTree(Object.keys(files));
  return (
    <div className="file-tree">
      {tree.map((item) => (
        <FileTreeNode
          key={item.type === "file" ? item.path : item.name}
          item={item}
          activeFile={activeFile}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}
