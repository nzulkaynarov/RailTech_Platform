import { theme } from "antd";

import { type BridgeEntry, routeTarget } from "../bridge";
import { useBridgeView } from "./useBridgeView";

const UNKNOWN: BridgeEntry = { who: "unknown", when: "pilot" };

/** Содержимое поповера «Где сделать» / «Где посмотреть»: где работа делается сейчас, кнопка «Открыть в …», когда появится. */
export function WhereToDo({ path }: { path: string }) {
  const { token } = theme.useToken();
  const target = routeTarget(path);
  const view = useBridgeView(target?.entry ?? UNKNOWN, target?.objectId, "short");
  const quiet = { margin: "8px 0 0", color: token.colorTextSecondary, fontSize: 12 };
  return (
    <div className="pf-where" style={{ maxWidth: 320 }}>
      <p style={{ margin: 0 }}>{view.intro}</p>
      {view.action ? <div style={{ marginTop: 8 }}>{view.action}</div> : null}
      {view.note ? <p style={quiet}>{view.note}</p> : null}
      <p style={quiet}>{view.when}</p>
    </div>
  );
}
