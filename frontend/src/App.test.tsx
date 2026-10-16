import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { App } from "./App";

test("bootstrap identifies the application without claiming live monitoring", () => {
  const html = renderToStaticMarkup(<App />);
  expect(html).toContain("Machine Monitor");
  expect(html).toContain("Nenhuma máquina está sendo monitorada");
});
