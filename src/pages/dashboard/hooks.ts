import { useEffect, useState, useCallback } from 'react';
import { remotePost } from '../../common/api-gateway';

export interface DailyJobCount {
  date: string;
  status: string;
  count: number;
}

export interface JobStats {
  total_count: number;
  by_status: Record<string, number>;
  by_type: Record<string, number>;
  daily_counts: DailyJobCount[];
}

export interface EndpointStats {
  total_count: number;
  by_deployment_target: Record<string, number>;
  by_status: Record<string, number>;
  by_engine: Record<string, number>;
}

export interface ClusterStats {
  total_count: number;
  active_count: number;
  by_status: Record<string, number>;
  total_instance_count: number;
  instance_type_distribution: Record<string, number>;
}

export interface DashboardStats {
  job_stats: JobStats;
  endpoint_stats: EndpointStats;
  cluster_stats: ClusterStats;
}

export function useDashboardStats() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchStats = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await remotePost({}, 'dashboard_stats');
      setStats(res as DashboardStats);
    } catch (err) {
      setError(err as Error);
      console.error('Error fetching dashboard stats:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  return { stats, loading, error, refresh: fetchStats };
}
