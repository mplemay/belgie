import { Widget } from "@belgie/mcp";

import { WeatherCard } from "./WeatherCard";
import "./styles.css";

export default function WeatherWidget() {
  return (
    <Widget metadata={{ name: "Weather", version: "1.0.0" }}>
      <WeatherCard city="Austin" condition="Sunny" temperature={32} />
    </Widget>
  );
}
