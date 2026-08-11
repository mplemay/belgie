import { Runtime, Script } from "@belgie/runtime";

async function typedUsage(): Promise<void> {
  await using runtime = await Runtime.create();
  const script = new Script<[number], { doubled: number }>(`
    export default function run(value: number) {
      return { doubled: value * 2 };
    }
  `);
  await using runner = await runtime.bind(script);
  const result: { doubled: number } = await runner.run(21);
  void result;
}

void typedUsage;
