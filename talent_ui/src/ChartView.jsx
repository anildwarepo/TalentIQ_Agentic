import React, { useMemo } from "react";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ScatterChart, Scatter, ZAxis,
} from "recharts";

const COLORS = ["#0D9488", "#3B82F6", "#10B981", "#F59E0B", "#8B5CF6", "#EF4444", "#0EA5E9", "#F97316"];

/**
 * Detect whether markdown text contains a table with numeric data.
 */
export function canChart(text) {
  if (!text) return false;
  const lines = text.split("\n").filter((l) => l.trim().startsWith("|"));
  if (lines.length < 3) return false; // header + separator + at least one data row
  // Check that at least one cell beyond the first column contains a number
  for (let i = 2; i < lines.length; i++) {
    const cells = lines[i].split("|").map((c) => c.trim()).filter(Boolean);
    if (cells.some((c, idx) => idx > 0 && /^[\d,.]+%?$/.test(c.replace(/,/g, "")))) {
      return true;
    }
  }
  return false;
}

function parseMarkdownTable(text) {
  const lines = text.split("\n").filter((l) => l.trim().startsWith("|"));
  if (lines.length < 3) return { headers: [], rows: [] };

  const parse = (line) => line.split("|").map((c) => c.trim()).filter(Boolean);

  const headers = parse(lines[0]);
  // lines[1] is the separator
  const rows = [];
  for (let i = 2; i < lines.length; i++) {
    const cells = parse(lines[i]);
    if (cells.length === 0) continue;
    const row = {};
    headers.forEach((h, idx) => {
      const raw = (cells[idx] || "").replace(/,/g, "").replace(/%$/, "");
      const num = Number(raw);
      row[h] = isNaN(num) ? cells[idx] || "" : num;
    });
    rows.push(row);
  }
  return { headers, rows };
}

/**
 * Detect the best chart type based on data shape.
 *
 * - radar:   Multiple numeric columns (3+) with few rows — candidate comparison
 * - scatter: Exactly 2 numeric columns — correlation plot
 * - bar:     Few rows (≤20) — categorical comparison
 * - line:    Many rows (>20) — trends / distributions
 */
function detectChartType(headers, rows, numericKeys) {
  // Radar: 3+ numeric dimensions, ≤15 items (candidate profiles, skill coverage)
  if (numericKeys.length >= 3 && rows.length <= 15) return "radar";
  // Scatter: exactly 2 numeric columns
  if (numericKeys.length === 2 && rows.length >= 3) return "scatter";
  // Bar vs line
  return rows.length <= 20 ? "bar" : "line";
}

/**
 * Reshape rows for radar chart: each row becomes a dimension spoke,
 * each original numeric column becomes a separate series (candidate/category).
 *
 * Input:  [{ Name: "Alice", Skills: 8, Certs: 5, Exp: 9 }, ...]
 * Output: [{ dimension: "Skills", Alice: 8, Bob: 7 }, { dimension: "Certs", Alice: 5, Bob: 9 }, ...]
 */
function reshapeForRadar(rows, labelKey, numericKeys) {
  return numericKeys.map((dim) => {
    const point = { dimension: dim };
    rows.forEach((row) => {
      point[String(row[labelKey] || `Item ${rows.indexOf(row) + 1}`)] = row[dim] ?? 0;
    });
    return point;
  });
}

export default function ChartView({ text }) {
  const { headers, rows } = useMemo(() => parseMarkdownTable(text), [text]);

  if (rows.length === 0) return <p style={{ color: "#6B7280" }}>No chart data found.</p>;

  const labelKey = headers[0];
  const numericKeys = headers.filter((h, i) => i > 0 && rows.some((r) => typeof r[h] === "number"));

  if (numericKeys.length === 0) return <p style={{ color: "#6B7280" }}>No numeric columns to chart.</p>;

  const chartType = detectChartType(headers, rows, numericKeys);

  if (chartType === "radar") {
    const radarData = reshapeForRadar(rows, labelKey, numericKeys);
    const seriesNames = rows.map((r) => String(r[labelKey] || ""));

    return (
      <ResponsiveContainer width="100%" height={400}>
        <RadarChart cx="50%" cy="50%" outerRadius="75%" data={radarData}>
          <PolarGrid stroke="#D1D5DB" />
          <PolarAngleAxis dataKey="dimension" tick={{ fill: "#374151", fontSize: 12 }} />
          <PolarRadiusAxis tick={{ fill: "#6B7280", fontSize: 10 }} />
          <Tooltip contentStyle={{ background: "#FFFFFF", border: "1px solid #E5E7EB", color: "#1F2937" }} />
          <Legend wrapperStyle={{ color: "#374151" }} />
          {seriesNames.map((name, i) => (
            <Radar
              key={name}
              name={name}
              dataKey={name}
              stroke={COLORS[i % COLORS.length]}
              fill={COLORS[i % COLORS.length]}
              fillOpacity={0.15}
              strokeWidth={2}
            />
          ))}
        </RadarChart>
      </ResponsiveContainer>
    );
  }

  if (chartType === "scatter") {
    return (
      <ResponsiveContainer width="100%" height={320}>
        <ScatterChart margin={{ top: 10, right: 30, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
          <XAxis dataKey={numericKeys[0]} name={numericKeys[0]} tick={{ fill: "#374151", fontSize: 12 }} />
          <YAxis dataKey={numericKeys[1]} name={numericKeys[1]} tick={{ fill: "#374151", fontSize: 12 }} />
          <ZAxis dataKey={labelKey} name={labelKey} />
          <Tooltip
            contentStyle={{ background: "#FFFFFF", border: "1px solid #E5E7EB", color: "#1F2937" }}
            formatter={(value, name) => [value, name]}
            labelFormatter={(_, payload) => payload?.[0]?.payload?.[labelKey] || ""}
          />
          <Legend wrapperStyle={{ color: "#374151" }} />
          <Scatter name={`${numericKeys[0]} vs ${numericKeys[1]}`} data={rows} fill={COLORS[0]} />
        </ScatterChart>
      </ResponsiveContainer>
    );
  }

  // Bar or Line chart (existing logic)
  return (
    <ResponsiveContainer width="100%" height={320}>
      {chartType === "bar" ? (
        <BarChart data={rows} margin={{ top: 10, right: 30, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
          <XAxis dataKey={labelKey} tick={{ fill: "#374151", fontSize: 12 }} />
          <YAxis tick={{ fill: "#374151", fontSize: 12 }} />
          <Tooltip contentStyle={{ background: "#FFFFFF", border: "1px solid #E5E7EB", color: "#1F2937" }} />
          <Legend wrapperStyle={{ color: "#374151" }} />
          {numericKeys.map((key, i) => (
            <Bar key={key} dataKey={key} fill={COLORS[i % COLORS.length]} />
          ))}
        </BarChart>
      ) : (
        <LineChart data={rows} margin={{ top: 10, right: 30, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
          <XAxis dataKey={labelKey} tick={{ fill: "#374151", fontSize: 12 }} />
          <YAxis tick={{ fill: "#374151", fontSize: 12 }} />
          <Tooltip contentStyle={{ background: "#FFFFFF", border: "1px solid #E5E7EB", color: "#1F2937" }} />
          <Legend wrapperStyle={{ color: "#374151" }} />
          {numericKeys.map((key, i) => (
            <Line key={key} type="monotone" dataKey={key} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={false} />
          ))}
        </LineChart>
      )}
    </ResponsiveContainer>
  );
}
