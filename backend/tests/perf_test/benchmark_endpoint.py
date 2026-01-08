#!/usr/bin/env python3
"""
Endpoint Concurrent Inference Performance Benchmark Tool

Usage:
    python benchmark_endpoint.py --base-url <url> --api-key <key> --model <name> --concurrency 10 --requests 100
"""

import asyncio
import argparse
import time
import statistics
from dataclasses import dataclass, field
from typing import List, Optional
import httpx
from openai import AsyncOpenAI


@dataclass
class RequestMetrics:
    """Metrics for a single request"""
    success: bool
    latency: float  # Total latency in seconds
    ttft: Optional[float] = None  # Time to first token (streaming only)
    tokens: int = 0  # Total tokens generated (for backward compatibility)
    input_tokens: int = 0  # Input/prompt tokens
    output_tokens: int = 0  # Output/completion tokens
    output_tokens_per_sec: float = 0.0  # Output tokens per second for this request
    content: str = ""  # Response content (for samples)
    error: Optional[str] = None


@dataclass
class BenchmarkResult:
    """Aggregated benchmark results"""
    total_requests: int
    successful_requests: int
    failed_requests: int
    total_duration: float

    # Latency statistics (seconds)
    avg_latency: float
    p50_latency: float
    p90_latency: float
    p95_latency: float
    p99_latency: float
    min_latency: float
    max_latency: float

    # Throughput
    requests_per_second: float
    tokens_per_second: float = 0.0

    # Token statistics
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    avg_input_tokens: float = 0.0
    avg_output_tokens: float = 0.0
    input_tokens_per_second: float = 0.0
    output_tokens_per_second: float = 0.0
    avg_output_tokens_per_sec_per_request: float = 0.0  # Average generation speed per request

    # Streaming metrics
    avg_ttft: Optional[float] = None
    p50_ttft: Optional[float] = None
    p90_ttft: Optional[float] = None

    errors: List[str] = field(default_factory=list)

    def print_summary(self):
        """Print formatted benchmark summary"""
        print("\n" + "="*60)
        print("BENCHMARK RESULTS")
        print("="*60)
        print(f"Total Requests:      {self.total_requests}")
        print(f"Successful:          {self.successful_requests}")
        print(f"Failed:              {self.failed_requests}")
        print(f"Success Rate:        {self.successful_requests/self.total_requests*100:.2f}%")
        print(f"Total Duration:      {self.total_duration:.2f}s")
        print()
        print(f"Requests/sec:        {self.requests_per_second:.2f}")
        if self.tokens_per_second > 0:
            print(f"Tokens/sec:          {self.tokens_per_second:.2f}")
        print()
        print("Token Statistics:")
        print(f"  Total Input:       {self.total_input_tokens:,} tokens")
        print(f"  Total Output:      {self.total_output_tokens:,} tokens")
        print(f"  Total:             {self.total_tokens:,} tokens")
        print(f"  Avg Input/req:     {self.avg_input_tokens:.1f} tokens")
        print(f"  Avg Output/req:    {self.avg_output_tokens:.1f} tokens")
        if self.input_tokens_per_second > 0:
            print(f"  Input tokens/sec:  {self.input_tokens_per_second:.2f} (overall throughput)")
        if self.output_tokens_per_second > 0:
            print(f"  Output tokens/sec: {self.output_tokens_per_second:.2f} (overall throughput)")
        if self.avg_output_tokens_per_sec_per_request > 0:
            print(f"  Avg output speed:  {self.avg_output_tokens_per_sec_per_request:.2f} tokens/sec/request")
        print()
        print("Latency Statistics (seconds):")
        print(f"  Average:           {self.avg_latency:.3f}")
        print(f"  Median (P50):      {self.p50_latency:.3f}")
        print(f"  P90:               {self.p90_latency:.3f}")
        print(f"  P95:               {self.p95_latency:.3f}")
        print(f"  P99:               {self.p99_latency:.3f}")
        print(f"  Min:               {self.min_latency:.3f}")
        print(f"  Max:               {self.max_latency:.3f}")

        if self.avg_ttft is not None:
            print()
            print("Time to First Token (TTFT) - seconds:")
            print(f"  Average:           {self.avg_ttft:.3f}")
            print(f"  Median (P50):      {self.p50_ttft:.3f}")
            print(f"  P90:               {self.p90_ttft:.3f}")

        if self.errors:
            print()
            print(f"Errors ({len(self.errors)} unique):")
            for error in set(self.errors[:10]):  # Show max 10 unique errors
                print(f"  - {error}")
        print("="*60 + "\n")


class EndpointBenchmark:
    """Benchmark runner for LLM endpoints"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
        verify_ssl: bool = False,
        timeout: float = 120.0
    ):
        self.base_url = base_url
        self.model_name = model_name
        self.client = AsyncOpenAI(
            base_url=f"https://{base_url}/v1" if not base_url.startswith("http") else base_url,
            api_key=api_key,
            http_client=httpx.AsyncClient(verify=verify_ssl, timeout=timeout),
        )

    async def send_request(
        self,
        prompt: str,
        max_tokens: int,
        stream: bool = False,
        capture_content: bool = False
    ) -> RequestMetrics:
        """Send a single inference request and measure metrics"""
        start_time = time.time()
        first_token_time = None
        total_tokens = 0
        input_tokens = 0
        output_tokens = 0
        content = ""

        try:
            if stream:
                response = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    stream=True,
                    stream_options={"include_usage": True}  # Request usage in streaming mode
                )

                content_chunks = []
                async for chunk in response:
                    if first_token_time is None and chunk.choices:
                        first_token_time = time.time()
                    if chunk.choices and chunk.choices[0].delta.content:
                        chunk_content = chunk.choices[0].delta.content
                        total_tokens += 1
                        if capture_content:
                            content_chunks.append(chunk_content)
                    # Extract usage from the final chunk
                    if hasattr(chunk, 'usage') and chunk.usage:
                        input_tokens = chunk.usage.prompt_tokens
                        output_tokens = chunk.usage.completion_tokens

                if capture_content:
                    content = "".join(content_chunks)
                ttft = first_token_time - start_time if first_token_time else None
            else:
                response = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    stream=False
                )
                ttft = None
                if response.usage:
                    input_tokens = response.usage.prompt_tokens
                    output_tokens = response.usage.completion_tokens
                    total_tokens = output_tokens
                if capture_content and response.choices:
                    content = response.choices[0].message.content or ""

            latency = time.time() - start_time
            # Calculate output tokens per second for this request
            output_tokens_per_sec = output_tokens / latency if latency > 0 and output_tokens > 0 else 0.0

            return RequestMetrics(
                success=True,
                latency=latency,
                ttft=ttft,
                tokens=total_tokens,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                output_tokens_per_sec=output_tokens_per_sec,
                content=content
            )

        except Exception as e:
            latency = time.time() - start_time
            return RequestMetrics(
                success=False,
                latency=latency,
                error=str(e)
            )

    async def run_benchmark(
        self,
        concurrency: int,
        total_requests: int,
        prompt: str,
        max_tokens: int,
        stream: bool = False,
        show_samples: int = 0
    ) -> BenchmarkResult:
        """Run concurrent benchmark"""
        print(f"Starting benchmark:")
        print(f"  Endpoint: {self.base_url}")
        print(f"  Model: {self.model_name}")
        print(f"  Concurrency: {concurrency}")
        print(f"  Total Requests: {total_requests}")
        print(f"  Max Tokens: {max_tokens}")
        print(f"  Stream: {stream}")
        if show_samples > 0:
            print(f"  Show Samples: {show_samples}")
        print(f"  Prompt: {prompt[:50]}..." if len(prompt) > 50 else f"  Prompt: {prompt}")
        print()

        # Create semaphore to limit concurrency
        semaphore = asyncio.Semaphore(concurrency)

        async def bounded_request(request_id: int):
            # Capture content for first N requests if show_samples is enabled
            capture = show_samples > 0 and request_id < show_samples
            async with semaphore:
                return await self.send_request(prompt, max_tokens, stream, capture_content=capture)

        # Start benchmark
        start_time = time.time()
        tasks = [bounded_request(i) for i in range(total_requests)]

        # Execute with progress tracking
        results: List[RequestMetrics] = []
        completed = 0
        samples_shown = 0

        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
            completed += 1

            # Print sample output
            if show_samples > 0 and samples_shown < show_samples and result.success and result.content:
                samples_shown += 1
                print(f"\n{'='*60}")
                print(f"Sample Output #{samples_shown}")
                print(f"{'='*60}")
                print(f"Latency: {result.latency:.2f}s | Output tokens: {result.output_tokens} | Speed: {result.output_tokens_per_sec:.1f} tokens/sec")
                if result.ttft:
                    print(f"TTFT: {result.ttft:.3f}s")
                print(f"{'-'*60}")
                # Truncate content if too long
                content_display = result.content if len(result.content) <= 500 else result.content[:500] + "..."
                print(content_display)
                print(f"{'='*60}\n")

            if completed % max(1, total_requests // 10) == 0:
                print(f"Progress: {completed}/{total_requests} requests completed")

        total_duration = time.time() - start_time

        # Calculate statistics
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        if not successful:
            raise RuntimeError("All requests failed!")

        latencies = [r.latency for r in successful]
        latencies_sorted = sorted(latencies)

        def percentile(data, p):
            k = (len(data) - 1) * p
            f = int(k)
            c = f + 1
            if c >= len(data):
                return data[-1]
            return data[f] + (k - f) * (data[c] - data[f])

        # TTFT statistics (if streaming)
        ttfts = [r.ttft for r in successful if r.ttft is not None]
        ttft_stats = None
        if ttfts:
            ttfts_sorted = sorted(ttfts)
            ttft_stats = {
                'avg': statistics.mean(ttfts),
                'p50': percentile(ttfts_sorted, 0.5),
                'p90': percentile(ttfts_sorted, 0.9),
            }

        # Token statistics
        total_tokens = sum(r.tokens for r in successful)
        total_input_tokens = sum(r.input_tokens for r in successful)
        total_output_tokens = sum(r.output_tokens for r in successful)
        total_all_tokens = total_input_tokens + total_output_tokens
        avg_input_tokens = total_input_tokens / len(successful) if successful else 0
        avg_output_tokens = total_output_tokens / len(successful) if successful else 0

        # Calculate average output tokens per second per request
        output_speeds = [r.output_tokens_per_sec for r in successful if r.output_tokens_per_sec > 0]
        avg_output_tokens_per_sec_per_request = statistics.mean(output_speeds) if output_speeds else 0.0

        return BenchmarkResult(
            total_requests=total_requests,
            successful_requests=len(successful),
            failed_requests=len(failed),
            total_duration=total_duration,
            avg_latency=statistics.mean(latencies),
            p50_latency=percentile(latencies_sorted, 0.5),
            p90_latency=percentile(latencies_sorted, 0.9),
            p95_latency=percentile(latencies_sorted, 0.95),
            p99_latency=percentile(latencies_sorted, 0.99),
            min_latency=min(latencies),
            max_latency=max(latencies),
            requests_per_second=len(successful) / total_duration,
            tokens_per_second=total_all_tokens / total_duration if total_all_tokens > 0 else 0,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_tokens=total_all_tokens,
            avg_input_tokens=avg_input_tokens,
            avg_output_tokens=avg_output_tokens,
            input_tokens_per_second=total_input_tokens / total_duration if total_input_tokens > 0 else 0,
            output_tokens_per_second=total_output_tokens / total_duration if total_output_tokens > 0 else 0,
            avg_output_tokens_per_sec_per_request=avg_output_tokens_per_sec_per_request,
            avg_ttft=ttft_stats['avg'] if ttft_stats else None,
            p50_ttft=ttft_stats['p50'] if ttft_stats else None,
            p90_ttft=ttft_stats['p90'] if ttft_stats else None,
            errors=[r.error for r in failed if r.error]
        )


async def main():
    parser = argparse.ArgumentParser(
        description="Benchmark LLM endpoint concurrent inference performance"
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="Base URL of the endpoint (e.g., k8s-hyperpod-alb-xxx.elb.amazonaws.com)"
    )
    parser.add_argument(
        "--api-key",
        required=True,
        help="API key for authentication"
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Model name"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Number of concurrent requests (default: 10)"
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=100,
        help="Total number of requests to send (default: 100)"
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=256,
        help="Maximum tokens to generate per request (default: 256)"
    )
    parser.add_argument(
        "--prompt",
        default="Write a short story about artificial intelligence.",
        help="Prompt to use for testing"
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        default=True,
        help="Use streaming mode (default: True)"
    )
    parser.add_argument(
        "--no-stream",
        dest="stream",
        action="store_false",
        help="Disable streaming mode"
    )
    parser.add_argument(
        "--verify-ssl",
        action="store_true",
        help="Verify SSL certificate (default: disabled for self-signed certs)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Request timeout in seconds (default: 120)"
    )
    parser.add_argument(
        "--show-samples",
        type=int,
        default=3,
        help="Number of sample outputs to display during testing (default: 3, set to 0 to disable)"
    )

    args = parser.parse_args()

    # Disable SSL warnings if not verifying
    if not args.verify_ssl:
        import warnings
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    benchmark = EndpointBenchmark(
        base_url=args.base_url,
        api_key=args.api_key,
        model_name=args.model,
        verify_ssl=args.verify_ssl,
        timeout=args.timeout
    )

    result = await benchmark.run_benchmark(
        concurrency=args.concurrency,
        total_requests=args.requests,
        prompt=args.prompt,
        max_tokens=args.max_tokens,
        stream=args.stream,
        show_samples=args.show_samples
    )

    result.print_summary()


if __name__ == "__main__":
    asyncio.run(main())
